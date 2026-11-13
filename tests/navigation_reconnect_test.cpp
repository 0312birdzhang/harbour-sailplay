#include "navigationhost.h"
#include "sailplayprovider.h"
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QTemporaryDir>
#include <QThread>
#include <cstdio>
#include <cstdlib>
#include <functional>

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "NAVIGATION_RECONNECT_FAILED line=%d %s\n", __LINE__, #condition); std::exit(1); } } while (false)

bool waitFor(const std::function<bool()> &ready, int timeout = 5000)
{
    QElapsedTimer elapsed;
    elapsed.start();
    while (!ready() && elapsed.elapsed() < timeout) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(1);
    }
    return ready();
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    if (argc == 3) {
        const SailplayApplication declaration = SailplayApplication::fromDesktopFile(QString::fromLocal8Bit(argv[1]));
        CHECK(declaration.navigationTemplate());
        SailplayNavigationHost host(QString::fromLocal8Bit(argv[2]));
        bool initial = false, lost = false, restored = false;
        QObject::connect(&host, &SailplayNavigationHost::changed, &app, [&]() {
            if (initial && !host.ready()) lost = true;
            if (!host.ready() || !host.mapReady()) return;
            CHECK(host.mapImage().size() == QSize(640, 360));
            if (!initial) {
                initial = true;
                fprintf(stderr, "LIVE_MAP_RECONNECT_INITIAL_READY\n");
            } else if (lost) {
                restored = true;
                fprintf(stderr, "LIVE_MAP_RECONNECT_PASS\n");
                app.quit();
            }
        });
        host.configureMap(640, 360);
        host.open(declaration, "Map");
        QTimer::singleShot(30000, &app, &QCoreApplication::quit);
        app.exec();
        CHECK(restored);
        return 0;
    }
    QTemporaryDir runtime;
    CHECK(runtime.isValid());
    auto bus = QDBusConnection::connectToBus(QDBusConnection::SessionBus, "navigation-reconnect-backend");
    const QString service = "org.example.SailplayNavigationReconnect";
    SailplayProvider provider(bus, "reconnect-map", {{"navigation", SailplayProvider::navigationGuidance()}}, {"navigation"});
    provider.setActionHandler("navigation.stop", [](qulonglong, const QVariantMap &) {});
    CHECK(provider.start() && bus.registerService(service));
    SailplayApplication declaration;
    declaration.valid = true;
    declaration.applicationId = "reconnect-map";
    declaration.service = service;
    declaration.path = "/org/sailplay/v1/App";
    declaration.presentation = "template";
    declaration.capabilities = QStringList{"navigation"};
    SailplayNavigationHost host(runtime.path());
    host.open(declaration, "Map");
    CHECK(waitFor([&]() { return host.ready(); }));
    CHECK(bus.unregisterService(service));
    CHECK(waitFor([&]() { return !host.ready(); }));
    // With no activation file, the daemon names the service in its activation
    // error. Reaching this error proves the host actively tried to restart it.
    CHECK(waitFor([&]() { return host.error().contains(service); }));
    CHECK(bus.registerService(service));
    CHECK(waitFor([&]() { return host.ready() && host.error().isEmpty(); }));
    host.setActive(false);
    CHECK(bus.unregisterService(service));
    CHECK(waitFor([&]() { return !host.ready(); }));
    waitFor([]() { return false; }, 400);
    CHECK(!host.error().contains(service));
    host.setActive(true);
    CHECK(waitFor([&]() { return host.error().contains(service); }));
    CHECK(bus.registerService(service));
    CHECK(waitFor([&]() { return host.ready(); }));
    CHECK(bus.unregisterService(service));
    CHECK(waitFor([&]() { return !host.ready(); }));
    host.close();
    waitFor([]() { return false; }, 400);
    CHECK(host.error().isEmpty() && host.applicationId().isEmpty());
    fprintf(stderr, "NAVIGATION_RECONNECT_PASS\n");
}
