#include "mapcanvas.h"
#include "sailplayprovider.h"

#include <QBuffer>
#include <QElapsedTimer>
#include <QGuiApplication>
#include <QPainter>
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
    bool malformed = false;
    QVector<QVariantMap> touches;
    provider.setActionHandler(QStringLiteral("navigation.map.frame"), [&](qulonglong request, const QVariantMap &parameters) {
        ++frames;
        check(parameters.value(QStringLiteral("width")) == 640 && parameters.value(QStringLiteral("height")) == 360,
            "host did not request its configured dimensions");
        provider.complete(request, {{QStringLiteral("image"), malformed ? QByteArray("bad JPEG") : jpeg},
            {QStringLiteral("width"), 320}, {QStringLiteral("height"), 160},
            {QStringLiteral("state"), QVariantMap{{QStringLiteral("place"), QStringLiteral("Test place")}}}});
    });
    provider.setActionHandler(QStringLiteral("navigation.map.touch"), [&](qulonglong request, const QVariantMap &parameters) {
        touches.append(parameters);
        provider.complete(request);
    });
    provider.setActionHandler(QStringLiteral("navigation.stop"), [&](qulonglong request, const QVariantMap &) {
        provider.complete(request);
    });
    check(provider.start(), "provider export failed");
    SailplayNavigationHost host(runtime.path());
    host.configureMap(640, 360);
    host.open(declaration, QStringLiteral("Canvas"));
    waitFor([&] { return host.mapReady(); });
    check(host.mapAvailable() && host.mapState().value(QStringLiteral("place")) == QStringLiteral("Test place"),
        "map capability or nested state unavailable");
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
        for (const QSize &size : {QSize(1920, 720), QSize(1280, 720), QSize(720, 1280), QSize(960, 1920)}) {
            item->setSize(size);
            check(map->width() == item->width() && map->height() == item->height(), "map canvas did not fill the card");
        }
        card->setProperty("compact", true);
        check(card->property("mapMode").toBool(), "compact navigation lost the map canvas");
        card.reset();
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
