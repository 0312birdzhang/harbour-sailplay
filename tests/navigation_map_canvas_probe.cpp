#include "mapcanvas.h"
#include "sailplayprovider.h"

#include <QBuffer>
#include <QElapsedTimer>
#include <QGuiApplication>
#include <QPainter>
#include <QMouseEvent>
#include <QQuickWindow>
#include <QQuickRenderControl>
#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QTemporaryDir>
#include <QThread>
#include <QVector>

#include <cstdio>
#include <cstdlib>
#include <functional>
#include <memory>
#include <limits>

namespace {
void check(bool value, const char *message)
{
    if (!value) { fprintf(stderr, "MAP_CANVAS_CHECK_FAILED %s\n", message); std::exit(1); }
}

void waitFor(const std::function<bool()> &ready, int timeout = 5000)
{
    QElapsedTimer timer;
    timer.start();
    while (!ready() && timer.elapsed() < timeout) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(1);
    }
    check(ready(), "event deadline exceeded");
}

QQuickItem *findItem(QQuickItem *root, const QString &name)
{
    if (root->objectName() == name) return root;
    for (auto *child : root->childItems()) {
        if (auto *found = findItem(child, name)) return found;
    }
    return nullptr;
}
}

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    qmlRegisterType<SailplayMapCanvas>("Sailplay", 1, 0, "MapCanvas");
    QTemporaryDir runtime;
    check(runtime.isValid(), "temporary runtime unavailable");
    const QString service = QStringLiteral("org.example.SailplayMapCanvas");
    auto bus = QDBusConnection::sessionBus();
    check(bus.registerService(service), "bus identity unavailable");
    SailplayApplication declaration;
    declaration.valid = true;
    declaration.applicationId = QStringLiteral("map-canvas-probe");
    declaration.service = service;
    declaration.path = QStringLiteral("/org/sailplay/v1/App");
    declaration.presentation = QStringLiteral("template");
    declaration.capabilities = QStringList{QStringLiteral("navigation"), QStringLiteral("navigation-map")};
    SailplayProvider provider(declaration.applicationId,
        {{QStringLiteral("navigation"), SailplayProvider::navigationGuidance()}}, declaration.capabilities);
    QImage image(320, 160, QImage::Format_RGB32);
    image.fill(Qt::red);
    QPainter source(&image);
    source.fillRect(160, 0, 160, 160, Qt::blue);
    source.end();
    QByteArray jpeg;
    QBuffer buffer(&jpeg);
    buffer.open(QIODevice::WriteOnly);
    check(image.save(&buffer, "JPEG"), "JPEG encoder unavailable");
    int frames = 0;
    QSize configuredSize(640, 360);
    bool malformed = false;
    bool bookmarked = false;
    bool holdBrowse = false;
    qulonglong heldBrowse = 0;
    QVector<QVariantMap> touches;
    QVector<QVariantMap> browseActions;
    QVector<QVariantMap> controlActions;
    int stops = 0;
    QVariantMap browser{{QStringLiteral("page"), QString()}, {QStringLiteral("query"), QString()},
        {QStringLiteral("rows"), QVariantList{QVariantMap{{QStringLiteral("id"), QStringLiteral("1/0")},
            {QStringLiteral("title"), QString::fromUtf8("测试目的地 🌍")}, {QStringLiteral("subtitle"), QStringLiteral("Address")},
            {QStringLiteral("kind"), QStringLiteral("place")}}}}, {QStringLiteral("searching"), false}};
    provider.setActionHandler(QStringLiteral("navigation.map.frame"), [&](qulonglong request, const QVariantMap &parameters) {
        ++frames;
        check(parameters.value(QStringLiteral("width")) == configuredSize.width()
            && parameters.value(QStringLiteral("height")) == configuredSize.height(),
            "host did not request its configured dimensions");
        provider.complete(request, {{QStringLiteral("image"), malformed ? QByteArray("bad JPEG") : jpeg},
            {QStringLiteral("width"), 320}, {QStringLiteral("height"), 160},
            {QStringLiteral("state"), QVariantMap{{QStringLiteral("place"), QStringLiteral("Test place")},
                {QStringLiteral("canStart"), true}, {QStringLiteral("bookmarked"), bookmarked},
                {QStringLiteral("browser"), browser}}}});
    });
    provider.setActionHandler(QStringLiteral("navigation.map.touch"), [&](qulonglong request, const QVariantMap &parameters) {
        touches.append(parameters);
        provider.complete(request);
    });
    provider.setActionHandler(QStringLiteral("navigation.stop"), [&](qulonglong request, const QVariantMap &) {
        ++stops;
        provider.complete(request);
    });
    provider.setActionHandler(QStringLiteral("navigation.map.control"), [&](qulonglong request, const QVariantMap &parameters) {
        controlActions.append(parameters);
        provider.complete(request);
    });
    provider.setActionHandler(QStringLiteral("navigation.map.browse"), [&](qulonglong request, const QVariantMap &parameters) {
        browseActions.append(parameters);
        const QString command = parameters.value(QStringLiteral("command")).toString();
        if (command == QStringLiteral("toggle-bookmark")) bookmarked = !bookmarked;
        else browser[QStringLiteral("page")] = command == QStringLiteral("close") ? QString() : command;
        if (holdBrowse) { heldBrowse = request; return; }
        provider.complete(request, browser);
    });
    check(provider.start(), "provider export failed");
    SailplayNavigationHost host(runtime.path());
    host.configureMap(640, 360);
    host.open(declaration, QStringLiteral("Canvas"));
    waitFor([&] { return host.mapReady(); });
    check(host.mapAvailable() && host.mapState().value(QStringLiteral("place")) == QStringLiteral("Test place"),
        "map capability or nested state unavailable");
    check(host.mapBrowser().value(QStringLiteral("rows")).toList().first().toMap().value(QStringLiteral("title"))
        == QString::fromUtf8("测试目的地 🌍"), "nested destination rows were not decoded");
    host.mapBrowse(QStringLiteral("search"), {{QStringLiteral("query"), QStringLiteral("Address")}});
    check(host.mapBrowseBusy(), "browsing request did not become busy");
    host.mapBrowse(QStringLiteral("history"));
    waitFor([&] { return !host.mapBrowseBusy() && host.mapBrowser().value(QStringLiteral("page")) == QStringLiteral("search"); });
    check(browseActions.size() == 1 && browseActions.first().value(QStringLiteral("query")) == QStringLiteral("Address"),
        "destination request parameters or concurrency bound failed");
    SailplayMapCanvas canvas;
    canvas.setProvider(&host);
    canvas.setSize(QSizeF(400, 400));
    QImage painted(400, 400, QImage::Format_RGB32);
    painted.fill(Qt::black);
    QPainter target(&painted);
    canvas.paint(&target);
    target.end();
    check(qRed(painted.pixel(40, 200)) > 200 && qBlue(painted.pixel(360, 200)) > 200
        && painted.pixel(200, 20) == qRgb(0, 0, 0), "aspect-fit paint is invalid");
    canvas.touch(QStringLiteral("press"), 200, 10);
    canvas.touch(QStringLiteral("release"), 200, 10);
    check(touches.isEmpty(), "letterbox input reached the provider");
    host.mapTouch(QStringLiteral("press"), std::numeric_limits<double>::quiet_NaN(), 0.5);
    host.mapTouch(QStringLiteral("press"), -0.1, 0.5);
    host.mapTouch(QStringLiteral("unknown"), 0.5, 0.5);
    check(touches.isEmpty(), "invalid input reached the provider");
    canvas.touch(QStringLiteral("press"), 200, 200);
    canvas.touch(QStringLiteral("move"), 240, 220);
    canvas.touch(QStringLiteral("release"), 240, 220);
    waitFor([&] { return touches.size() == 3; });
    check(touches.at(0).value(QStringLiteral("x")).toDouble() == 0.5
        && touches.at(0).value(QStringLiteral("y")).toDouble() == 0.5
        && touches.at(2).value(QStringLiteral("phase")) == QStringLiteral("release"), "normalized gesture ordering failed");
    host.setActive(false);
    waitFor([&] { return provider.activeSessionCount() == 0 && touches.size() == 4; });
    const int hiddenFrames = frames;
    QElapsedTimer delay;
    delay.start();
    waitFor([&] { return delay.elapsed() > 500; });
    check(frames == hiddenFrames && provider.sessionCount() == 1, "hidden map kept polling or lost its lease");
    if (argc == 2) {
        QQmlEngine engine;
        engine.rootContext()->setContextProperty(QStringLiteral("probeHost"), &host);
        engine.rootContext()->setContextProperty(QStringLiteral("carController"),
            QVariantMap{{QStringLiteral("dayTheme"), false}});
        QQmlComponent component(&engine);
        const QString qml = QStringLiteral("import QtQuick 2.0\nimport QtQuick.Window 2.0\nimport \"%1\" as Ui\n"
            "Ui.NavigationCard { width: 640; height: 360; provider: probeHost; palette: Ui.CarPalette {} }")
            .arg(QUrl::fromLocalFile(QString::fromLocal8Bit(argv[1])).toString());
        component.setData(qml.toUtf8(), QUrl());
        waitFor([&] { return component.status() != QQmlComponent::Loading; });
        std::unique_ptr<QObject> card(component.create());
        for (const QQmlError &error : component.errors()) fprintf(stderr, "%s\n", qPrintable(error.toString()));
        check(card && card->property("mapMode").toBool(), "navigation QML did not expose the map canvas");
        auto *item = qobject_cast<QQuickItem *>(card.get());
        auto *map = card->findChild<SailplayMapCanvas *>(QStringLiteral("navigationMapCanvas"));
        check(item && map && map->provider() == &host, "navigation QML did not bind the map provider");
        const auto bounds = [&](QQuickItem *target) {
            check(target, "layout target is missing");
            return target->mapRectToItem(item, QRectF(0, 0, target->width(), target->height()));
        };
        const auto contained = [&](QQuickItem *target) {
            check(QRectF(0, 0, item->width(), item->height()).adjusted(-0.1, -0.1, 0.1, 0.1).contains(bounds(target)),
                "map control exceeded the viewport");
        };
        for (const QSize &size : {QSize(1920, 720), QSize(1748, 688), QSize(1106, 656), QSize(1280, 720),
                                 QSize(800, 480), QSize(640, 360), QSize(720, 1280), QSize(960, 1920)}) {
            item->setSize(size);
            check(map->width() == item->width() && map->height() == item->height(), "map canvas did not fill the card");
            card->setProperty("panelOpen", true);
            auto *panel = card->findChild<QQuickItem *>(QStringLiteral("navigationDestinationPanel"));
            contained(panel);
            auto *input = card->findChild<QQuickItem *>(QStringLiteral("navigationSearchInput"));
            check(input && input->width() > 0, "destination search input has no width");
            contained(card->findChild<QQuickItem *>(QStringLiteral("navigationDestinationBackButton")));
            contained(card->findChild<QQuickItem *>(QStringLiteral("navigationDestinationCloseButton")));
            card->setProperty("panelOpen", false);
            auto *toolbar = card->findChild<QQuickItem *>(QStringLiteral("navigationMapToolbar"));
            auto *preview = card->findChild<QQuickItem *>(QStringLiteral("navigationRoutePreview"));
            auto *settings = card->findChild<QQuickItem *>(QStringLiteral("navigationSettingsButton"));
            contained(toolbar);
            contained(preview);
            contained(settings);
            check(bounds(toolbar).right() < bounds(settings).left(), "toolbar overlaps settings");
            check(bounds(preview).width() <= item->width() * 0.5, "route preview consumes too much map space");
            for (const QString &name : {QStringLiteral("navigationDestinationButton"),
                                       QStringLiteral("navigationBookmarksButton"),
                                       QStringLiteral("navigationRouteActionButton"),
                                       QStringLiteral("navigationPreviewCloseButton"),
                                       QStringLiteral("navigationMapControl_position"),
                                       QStringLiteral("navigationMapControl_zoom-in"),
                                       QStringLiteral("navigationMapControl_zoom-out")}) {
                auto *button = findItem(item, name);
                contained(button);
                if (size == QSize(1748, 688)) check(bounds(button).height() >= 100, "full map touch target is too small");
                if (size == QSize(1106, 656)) check(bounds(button).height() >= 80, "split map touch target is too small");
            }
            auto *controls = card->findChild<QQuickItem *>(QStringLiteral("navigationMapControls"));
            check(!bounds(controls).intersects(bounds(preview)), "map buttons overlap the route preview");
            printf("NAVIGATION_CONTROL_LAYOUT_PASS %dx%d destination=%.1f position=%.1f\n", size.width(), size.height(),
                bounds(card->findChild<QQuickItem *>(QStringLiteral("navigationDestinationButton"))).height(),
                bounds(findItem(item, QStringLiteral("navigationMapControl_position"))).height());
        }

        configuredSize = QSize(1280, 720);
        item->setSize(configuredSize);
        QQuickRenderControl layout;
        QQuickWindow window(&layout);
        window.resize(configuredSize);
        item->setParentItem(window.contentItem());
        window.show();
        host.setActive(true);
        waitFor([&] { return provider.activeSessionCount() == 1; });
        const auto click = [&](QQuickItem *target, const QPointF &local) {
            layout.polishItems();
            check(target && target->isVisible(), "click target is unavailable");
            const QPointF point = target->mapToScene(local);
            QMouseEvent press(QEvent::MouseButtonPress, point, Qt::LeftButton, Qt::LeftButton, Qt::NoModifier);
            QCoreApplication::sendEvent(&window, &press);
            QMouseEvent release(QEvent::MouseButtonRelease, point, Qt::LeftButton, Qt::NoButton, Qt::NoModifier);
            QCoreApplication::sendEvent(&window, &release);
            QElapsedTimer settling;
            settling.start();
            waitFor([&] { return settling.elapsed() > 120; });
        };
        const int beforeOverlay = touches.size();
        auto *preview = card->findChild<QQuickItem *>(QStringLiteral("navigationRoutePreview"));
        auto *previewText = card->findChild<QQuickItem *>(QStringLiteral("navigationPreviewText"));
        click(previewText, QPointF(20, previewText->height() / 2));
        click(preview, QPointF(preview->width() - 8, 20));
        auto *toolbar = card->findChild<QQuickItem *>(QStringLiteral("navigationMapToolbar"));
        auto *destination = card->findChild<QQuickItem *>(QStringLiteral("navigationDestinationButton"));
        click(toolbar, QPointF(destination->width() + 4, toolbar->height() / 2));
        check(touches.size() == beforeOverlay, "preview text, padding or toolbar gap reached the map");

        auto *bookmarks = card->findChild<QQuickItem *>(QStringLiteral("navigationBookmarksButton"));
        auto *bookmarkIcon = card->findChild<QQuickItem *>(QStringLiteral("navigationBookmarksIcon"));
        check(bookmarkIcon && bookmarkIcon->isVisible() && bookmarkIcon->property("filled").toBool(),
            "bookmark entry icon is missing");
        click(bookmarks, QPointF(bookmarks->width() / 2, bookmarks->height() / 2));
        waitFor([&] { return !host.mapBrowseBusy() && host.mapBrowser().value(QStringLiteral("page")) == QStringLiteral("bookmark-groups"); });
        check(card->property("panelOpen").toBool(), "bookmark entry did not open the destination panel");
        auto *panel = card->findChild<QQuickItem *>(QStringLiteral("navigationDestinationPanel"));
        click(panel, QPointF(panel->width() - 4, panel->height() - 4));
        check(touches.size() == beforeOverlay, "destination panel bottom reached the map");
        check(QMetaObject::invokeMethod(panel, "closePanel"), "destination panel close is unavailable");
        waitFor([&] { return !host.mapBrowseBusy() && !card->property("panelOpen").toBool(); });
        auto *bookmarkPlace = card->findChild<QQuickItem *>(QStringLiteral("navigationBookmarkPlaceButton"));
        auto *placeIcon = card->findChild<QQuickItem *>(QStringLiteral("navigationBookmarkPlaceIcon"));
        check(placeIcon && placeIcon->isVisible() && !placeIcon->property("filled").toBool(),
            "unbookmarked place icon is missing");
        click(bookmarkPlace, QPointF(bookmarkPlace->width() / 2, bookmarkPlace->height() / 2));
        waitFor([&] { return placeIcon->property("filled").toBool(); });
        check(browseActions.last().value(QStringLiteral("command")) == QStringLiteral("toggle-bookmark")
            && touches.size() == beforeOverlay, "bookmark action reached the map or failed to toggle");
        holdBrowse = true;
        host.mapBrowse(QStringLiteral("history"));
        waitFor([&] { return heldBrowse != 0; });
        auto *settings = card->findChild<QQuickItem *>(QStringLiteral("navigationSettingsButton"));
        click(settings, QPointF(settings->width() / 2, settings->height() / 2));
        click(bookmarkPlace, QPointF(bookmarkPlace->width() / 2, bookmarkPlace->height() / 2));
        check(touches.size() == beforeOverlay, "disabled map controls reached the map");
        holdBrowse = false;
        provider.complete(heldBrowse, browser);
        waitFor([&] { return !host.mapBrowseBusy(); });
        for (const QString &command : {QStringLiteral("position"), QStringLiteral("zoom-in"), QStringLiteral("zoom-out")}) {
            auto *button = findItem(item, QStringLiteral("navigationMapControl_") + command);
            click(button, QPointF(button->width() - 2, button->height() - 2));
            check(!controlActions.isEmpty() && controlActions.last().value(QStringLiteral("command")) == command,
                "scaled map button edge did not invoke its command");
        }
        auto *start = card->findChild<QQuickItem *>(QStringLiteral("navigationRouteActionButton"));
        click(start, QPointF(start->width() - 2, start->height() - 2));
        check(controlActions.last().value(QStringLiteral("command")) == QStringLiteral("start")
            && touches.size() == beforeOverlay, "scaled start button edge reached the map or missed its action");
        check(provider.publish({{QStringLiteral("navigation"), SailplayProvider::navigationGuidance(QStringLiteral("active"))}}),
            "active guidance was rejected");
        waitFor([&] { return card->property("navigating").toBool(); });
        check(!bookmarks->isVisible() && !start->isVisible(), "planning buttons remained visible during navigation");
        check(provider.publish({{QStringLiteral("navigation"), SailplayProvider::navigationGuidance(QStringLiteral("unavailable"))}}),
            "temporarily unavailable guidance was rejected");
        waitFor([&] { return !card->property("guidanceAvailable").toBool(); });
        check(card->property("navigating").toBool() && !preview->isVisible() && !bookmarks->isVisible(),
            "navigation controls were lost or stale directions remained visible");
        click(settings, QPointF(settings->width() - 2, settings->height() - 2));
        check(stops == 1 && touches.size() == beforeOverlay, "scaled stop button edge did not stop navigation");
        check(provider.publish({{QStringLiteral("navigation"), SailplayProvider::navigationGuidance()}}), "idle guidance was rejected");
        waitFor([&] { return !card->property("navigating").toBool(); });
        click(item, QPointF(900, 400));
        waitFor([&] { return touches.size() >= beforeOverlay + 2; });
        check(touches.last().value(QStringLiteral("phase")) == QStringLiteral("release"),
            "uncovered map input did not finish its gesture");
        puts("NAVIGATION_MAP_OVERLAY_PASS preview-text padding toolbar-gap destination-bottom bookmark-entry bookmark-toggle disabled-controls scaled-button-edges start-stop uncovered-map");
        window.hide();
        host.setActive(false);
        card->setProperty("compact", true);
        check(card->property("mapMode").toBool(), "compact navigation lost the map canvas");
        check(card->findChild<QObject *>(QStringLiteral("navigationDestinationPanel"))
            && card->findChild<QObject *>(QStringLiteral("navigationSearchInput")), "destination search UI is missing");
        card.reset();
        configuredSize = QSize(640, 360);
        host.configureMap(640, 360);
    }
    malformed = true;
    host.setActive(true);
    waitFor([&] { return !host.error().isEmpty(); });
    malformed = false;
    waitFor([&] { return host.error().isEmpty() && frames > hiddenFrames + 1; });
    provider.close();
    bus.unregisterService(service);
    waitFor([&] { return !host.ready() && !host.mapReady(); });
    host.close();
    puts("NAVIGATION_MAP_CANVAS_PASS jpeg aspect-fit input ordering hidden-lease invalid-frame retry owner-loss");
    return 0;
}
