#include "../display-source/carui/contenthost.h"
#include "sailplaycontent.h"
#include "sailplayprovider.h"

#include <QDBusArgument>
#include <QDBusObjectPath>
#include <QDBusPendingCallWatcher>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QGuiApplication>
#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickRenderControl>
#include <QQuickWindow>
#include <QThread>

#include <cstdio>
#include <cstdlib>
#include <functional>
#include <memory>

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "CONTENT_HOST_CHECK_FAILED line=%d %s\n", __LINE__, #condition); std::exit(1); } } while (false)

namespace {
bool waitFor(const std::function<bool()> &ready, int timeout = 3000)
{
    QElapsedTimer elapsed;
    elapsed.start();
    while (!ready() && elapsed.elapsed() < timeout) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(1);
    }
    return ready();
}

QDBusMessage call(const QDBusConnection &bus, const QString &path, const QString &interface, const QString &member,
                  const QVariantList &arguments = QVariantList())
{
    auto message = QDBusMessage::createMethodCall("org.example.NativeContent", path, interface, member);
    message.setArguments(arguments);
    QDBusPendingCallWatcher watcher(bus.asyncCall(message, 2000));
    CHECK(waitFor([&]() { return watcher.isFinished(); }));
    return watcher.reply();
}
}

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    app.setQuitOnLastWindowClosed(false);
    if (argc > 1 && QString::fromLocal8Bit(argv[1]) == QStringLiteral("--python-provider")) {
        SailplayApplication declaration;
        declaration.valid = declaration.declared = true;
        declaration.applicationId = "sailplay-content-example";
        declaration.service = "org.example.SailplayContent";
        declaration.path = "/org/sailplay/v1/App";
        declaration.presentation = "template";
        declaration.capabilities = QStringList{"content"};
        SailplayContentHost host;
        host.open(declaration, "Python content");
        CHECK(waitFor([&]() { return host.ready() && host.items().size() == 1; }));
        host.select("library");
        CHECK(waitFor([&]() { return !host.busy() && host.items().size() == 50; }));
        host.more();
        CHECK(waitFor([&]() { return !host.busy() && host.items().size() == 100; }));
        host.search("Item 12");
        CHECK(waitFor([&]() { return !host.busy() && host.items().size() == 6; }));
        host.select("item-12");
        CHECK(waitFor([&]() { return !host.busy(); }));
        host.back();
        CHECK(waitFor([&]() { return !host.busy() && host.items().size() == 50; }));
        host.back();
        CHECK(host.page().value("message") == "Selected item-12");
        host.close();
        fprintf(stderr, "CONTENT_PYTHON_QT_PASS typed-map-arrays browsing pagination search actions messages\n");
        return 0;
    }
    if (argc > 1 && QString::fromLocal8Bit(argv[1]) == QStringLiteral("--presentation")) {
        // Tabs, a split page and a pinned side panel, as a podcast or music player would ask for.
        qulonglong version = 1;
        QStringList queue = {"q1", "q2"};
        const auto folder = [](const QString &id, const QString &title) { return SailplayContent::item(id, title); };
        const auto rootPage = [&]() {
            QVariantMap page = SailplayContent::page("root", "Player");
            page["version"] = version;
            page["items"] = QVariantList{folder("queue", "Queue"), folder("subs", "Subscriptions"), folder("news", "New")};
            return page;
        };
        const QVariantMap rootHints = SailplayContent::presentation(QString(), true, "queue");
        CHECK(rootHints.value("tabs").toBool() && rootHints.value("side") == "queue");
        SailplayProvider provider("native-content", {{"content", rootPage()}, {"contentPresentation", rootHints}}, {"content"});
        const auto browse = [&](qulonglong invocation, const QVariantMap &parameters) {
            const QString id = parameters.value("id").toString();
            QVariantMap page = SailplayContent::page(id, id.toUpper());
            page["version"] = version;
            page["offset"] = parameters.value("offset").toUInt();
            QVariantMap hints;
            QVariantList entries;
            if (id == "queue") {
                for (const QString &track : queue)
                    entries.append(SailplayContent::item(track, "Track " + track, "action", "content.play", {{"id", track}}));
                CHECK(SailplayContent::hint(hints, queue.first(), QString(), "playing"));
                page["actions"] = QVariantList{SailplayContent::item("clear", "Clear", "action", "content.clear")};
            } else if (id == "subs") {
                hints = SailplayContent::presentation("split");
                entries = QVariantList{folder("p1", "Podcast 1"), folder("p2", "Podcast 2")};
                CHECK(SailplayContent::hint(hints, "p1", "/tmp/p1.png"));
                CHECK(!SailplayContent::hint(hints, "p2", "relative.png"));
            } else if (id == "news") {
                hints = SailplayContent::presentation("grid");
                entries = QVariantList{SailplayContent::item("n1", "New 1", "action", "content.add", {{"id", "n1"}})};
            } else if (id == "p1" || id == "p2") {
                hints = SailplayContent::presentation("split");   // ignored in a detail area
                for (const QString &episode : {QStringLiteral("a"), QStringLiteral("b")})
                    entries.append(SailplayContent::item(id + episode, "Episode " + episode, "action", "content.add",
                                                         {{"id", id + episode}}));
                CHECK(SailplayContent::hint(hints, id + "a", QString(), "started"));
            }
            page["items"] = entries;
            QVariantMap result{{"content", page}};
            if (!hints.isEmpty()) result.insert("presentation", hints);
            CHECK(provider.complete(invocation, result));
        };
        provider.setActionHandler("content.browse", browse);
        provider.setActionHandler("content.search", browse);
        const auto changeQueue = [&](qulonglong invocation, const QVariantMap &parameters, bool clear) {
            if (clear) queue = QStringList{"q1"}; else queue.append(parameters.value("id").toString());
            ++version;
            CHECK(provider.publish({{"content", rootPage()}, {"contentPresentation", rootHints}}));
            CHECK(provider.complete(invocation));
        };
        provider.setActionHandler("content.add", [&](qulonglong i, const QVariantMap &p) { changeQueue(i, p, false); });
        provider.setActionHandler("content.clear", [&](qulonglong i, const QVariantMap &p) { changeQueue(i, p, true); });
        provider.setActionHandler("content.play", [&](qulonglong i, const QVariantMap &) { CHECK(provider.complete(i)); });
        CHECK(provider.start());
        CHECK(QDBusConnection::sessionBus().registerService("org.example.NativeContent"));
        SailplayApplication declaration;
        declaration.valid = declaration.declared = true;
        declaration.applicationId = "native-content";
        declaration.service = "org.example.NativeContent";
        declaration.path = "/org/sailplay/v1/App";
        declaration.presentation = "template";
        declaration.capabilities = QStringList{"content"};
        SailplayContentHost host;
        int activations = 0;
        QObject::connect(&host, &SailplayContentHost::itemActivated, &app, [&](const QString &) { ++activations; });
        host.open(declaration, "Player");
        const auto settled = [&]() { return host.ready() && !host.busy(); };
        const auto rows = [](const QVariantMap &pane) { return pane.value("items").toList(); };
        // The pinned folder is a panel, not a tab; the first tab is a split page with its first folder chosen.
        CHECK(waitFor([&]() { return settled() && rows(host.side()).size() == 2 && rows(host.detail()).size() == 2; }));
        CHECK(host.tabs().size() == 2 && host.currentTab() == "subs" && !host.canGoBack());
        CHECK(host.layout() == "split" && host.items().size() == 2 && host.currentItem() == "p1");
        CHECK(host.items().first().toMap().value("image") == "/tmp/p1.png");
        CHECK(host.items().last().toMap().value("image").toString().isEmpty());
        CHECK(host.detail().value("id") == "p1" && host.detail().value("layout") == "list");
        CHECK(rows(host.detail()).first().toMap().value("playback") == "started");
        CHECK(host.side().value("id") == "queue" && host.side().value("actions").toList().size() == 1);
        CHECK(rows(host.side()).first().toMap().value("playback") == "playing");
        // Choosing another folder of a split page replaces the right side and adds no history.
        host.select("p2");
        CHECK(waitFor([&]() { return settled() && host.detail().value("id") == "p2"; }));
        CHECK(host.currentItem() == "p2" && !host.canGoBack() && host.currentTab() == "subs");
        CHECK(rows(host.detail()).first().toMap().value("id") == "p2a");
        // An action on the right changes the queue: the panel follows and the page stays.
        host.selectDetail("p2b");
        CHECK(waitFor([&]() { return settled() && rows(host.side()).size() == 3; }));
        CHECK(activations == 0 && host.currentItem() == "p2" && host.currentTab() == "subs");
        CHECK(waitFor([&]() { return settled() && host.detail().value("id") == "p2"; }));
        // Another tab has its own arrangement and no detail.
        host.selectTab("news");
        CHECK(waitFor([&]() { return settled() && host.currentTab() == "news" && host.items().size() == 1; }));
        CHECK(host.layout() == "grid" && host.currentItem().isEmpty() && host.detail().isEmpty());
        host.select("n1");
        CHECK(waitFor([&]() { return settled() && rows(host.side()).size() == 4; }));
        CHECK(host.currentTab() == "news" && activations == 0);
        // The panel's own controls and rows.
        host.sideAction("clear");
        CHECK(waitFor([&]() { return settled() && rows(host.side()).size() == 1; }));
        host.selectSide("q1");
        CHECK(waitFor([&]() { return settled(); }));
        CHECK(rows(host.side()).size() == 1 && host.tabs().size() == 2);
        host.close();
        CHECK(host.side().isEmpty() && host.detail().isEmpty() && host.tabs().isEmpty());
        CHECK(waitFor([&]() { return provider.sessionCount() == 0; }));
        provider.close();
        fprintf(stderr, "CONTENT_PRESENTATION_PASS tabs split side-panel hints actions\n");
        return 0;
    }
    QVariantMap root = SailplayContent::page("root", "Content 中文");
    root["items"] = QVariantList{SailplayContent::item("library", "Library")};
    root["searchEnabled"] = true;
    root["actions"] = QVariantList{SailplayContent::item("stop", "Stop", "action", "content.stop")};
    SailplayProvider provider("native-content", {{"content", root}}, {"content"});
    qulonglong slow = 0;
    int browseCount = 0;
    QVariantMap slowPage;
    const auto browse = [&](qulonglong invocation, const QVariantMap &parameters) {
        ++browseCount;
        auto page = SailplayContent::page(parameters.value("id").toString(), parameters.value("query", "Library").toString());
        page["version"] = root.value("version");
        page["searchEnabled"] = true;
        const uint offset = parameters.value("offset").toUInt();
        page["offset"] = offset;
        QVariantList entries;
        for (uint index = offset; index < qMin(uint(125), offset + parameters.value("limit").toUInt()); ++index)
            entries.append(SailplayContent::item(QString::number(index), "Item " + QString::number(index), "action", "content.stop"));
        page["items"] = entries;
        page["hasMore"] = offset + entries.size() < 125;
        if (parameters.value("query") == "older") { slow = invocation; slowPage = page; return; }
        CHECK(provider.complete(invocation, {{"content", page}}));
    };
    provider.setActionHandler("content.browse", browse);
    provider.setActionHandler("content.search", browse);
    provider.setActionHandler("content.stop", [&](qulonglong invocation, const QVariantMap &) {
        root["message"] = "Stopped";
        root["messageKind"] = "info";
        CHECK(provider.publish({{"content", root}}));
        CHECK(provider.complete(invocation));
    });
    CHECK(provider.start());
    CHECK(QDBusConnection::sessionBus().registerService("org.example.NativeContent"));
    SailplayApplication declaration;
    declaration.valid = declaration.declared = true;
    declaration.applicationId = "native-content";
    declaration.desktopId = "native-content-shortcut";
    declaration.service = "org.example.NativeContent";
    declaration.path = "/org/sailplay/v1/App";
    declaration.presentation = "template";
    declaration.capabilities = QStringList{"content"};
    SailplayContentHost host;
    QStringList activated;
    QObject::connect(&host, &SailplayContentHost::itemActivated, &app,
                     [&](const QString &id) { activated.append(id); });
    host.open(declaration, "Content");
    CHECK(waitFor([&]() { return host.ready() && host.items().size() == 1; }));
    CHECK(host.applicationId() == "native-content-shortcut");
    host.select("library");
    CHECK(waitFor([&]() { return !host.busy() && host.items().size() == 50; }));
    CHECK(host.page().value("id") == "library" && host.canGoBack());
    host.more();
    CHECK(waitFor([&]() { return !host.busy() && host.items().size() == 100; }));
    host.more();
    CHECK(waitFor([&]() { return !host.busy() && host.items().size() == 125; }));
    CHECK(!host.page().value("hasMore").toBool());
    const int queriesBeforeProgress = browseCount;
    int changes = 0;
    QObject::connect(&host, &SailplayContentHost::changed, &app, [&]() { ++changes; });
    CHECK(provider.publish({{"content", root}, {"media", QVariantMap{{"position", qlonglong(12000)}}}}));
    CHECK(waitFor([&]() { return changes > 0; }));
    CHECK(host.items().size() == 125 && browseCount == queriesBeforeProgress && !host.busy());
    host.search("older");
    CHECK(waitFor([&]() { return slow != 0; }));
    host.search("newer");
    CHECK(waitFor([&]() { return !host.busy() && host.page().value("title") == "newer"; }));
    CHECK(provider.complete(slow, {{"content", slowPage}}));
    CHECK(waitFor([&]() { return provider.pendingCount() == 0; }));
    CHECK(host.page().value("title") == "newer");
    host.back();
    CHECK(waitFor([&]() { return !host.busy() && host.page().value("title") == "Library"; }));
    host.back();
    CHECK(host.page().value("id") == "root");
    host.action("stop");
    CHECK(waitFor([&]() { return !host.busy() && host.page().value("message") == "Stopped"; }));
    // Folders and page controls are not activations; a list item's action is.
    CHECK(activated.isEmpty());
    host.select("library");
    CHECK(waitFor([&]() { return !host.busy() && host.items().size() == 50; }));
    CHECK(activated.isEmpty());
    host.select("7");
    CHECK(waitFor([&]() { return !host.busy() && activated.size() == 1; }));
    CHECK(activated.first() == "7");
    host.setActive(false);
    CHECK(waitFor([&]() { return provider.sessionCount() == 1 && provider.activeSessionCount() == 0; }));

    auto owner = QDBusConnection::connectToBus(QDBusConnection::SessionBus, "content-owner");
    auto intruder = QDBusConnection::connectToBus(QDBusConnection::SessionBus, "content-intruder");
    auto reply = call(owner, "/org/sailplay/v1/App", "org.sailplay.App1", "OpenSession", {"phone", QStringList{"content"}});
    CHECK(reply.type() == QDBusMessage::ReplyMessage);
    const QString path = qdbus_cast<QDBusObjectPath>(reply.arguments().first()).path();
    reply = call(owner, path, "org.sailplay.Content1", "GetContent");
    CHECK(reply.signature() == "ta{sv}" && SailplayContent::validPage(SailplayContent::decode(reply.arguments()[1]).toMap()));
    reply = call(owner, path, "org.freedesktop.DBus.Properties", "GetAll", {"org.sailplay.Content1"});
    CHECK(reply.type() == QDBusMessage::ReplyMessage && qdbus_cast<QVariantMap>(reply.arguments().first()).isEmpty());
    reply = call(intruder, path, "org.sailplay.Content1", "GetContent");
    CHECK(reply.errorName() == "org.sailplay.Error1.NotOwner");
    reply = call(owner, path, "org.sailplay.Session1", "Invoke", {QVariant::fromValue(qulonglong(1)), "content.browse",
        QVariantMap{{"id", "root"}, {"offset", uint(0)}, {"limit", uint(51)}}, QVariant::fromValue(qulonglong(0))});
    CHECK(reply.errorName() == "org.sailplay.Error1.InvalidArgument");
    CHECK(call(owner, path, "org.sailplay.Session1", "Close").type() == QDBusMessage::ReplyMessage);

    if (argc > 1) {
        QQmlEngine engine;
        QQmlComponent component(&engine, QUrl::fromLocalFile(QString::fromLocal8Bit(argv[1])));
        std::unique_ptr<QObject> object(component.beginCreate(engine.rootContext()));
        if (!object) for (const auto &error : component.errors()) fprintf(stderr, "%s\n", qPrintable(error.toString()));
        CHECK(object);
        object->setProperty("provider", QVariant::fromValue<QObject *>(&host));
        object->setProperty("palette", QVariantMap{{"card", "#111111"}, {"button", "#333333"}, {"text", "white"},
            {"secondary", "#cccccc"}, {"notice", "#555555"}});
        component.completeCreate();
        QQuickRenderControl layout;
        QQuickWindow window(&layout);
        auto item = qobject_cast<QQuickItem *>(object.get());
        CHECK(item);
        item->setParentItem(window.contentItem());
        for (const QSize size : {QSize(1780, 688), QSize(1140, 688), QSize(580, 1248)}) {
            item->setSize(size);
            app.processEvents();
            layout.polishItems();
            auto list = item->findChild<QQuickItem *>("contentList");
            CHECK(list && list->width() > 0 && list->height() > 0 && list->y() + list->height() <= item->height());
        }
        item->setParentItem(nullptr);
    }
    host.close();
    CHECK(waitFor([&]() { return provider.sessionCount() == 0; }));
    provider.close();
    fprintf(stderr, "CONTENT_HOST_PASS ownership bounded-queries browsing pagination search ordering actions messages hidden-lease qml-geometry\n");
}
