#include "sailplayprovider.h"
#include "sailplaysession.h"
#include "musichost.h"

#include <QCoreApplication>
#include <QDBusArgument>
#include <QDBusConnectionInterface>
#include <QDBusPendingCallWatcher>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QTemporaryDir>
#include <QThread>
#include <cstdio>
#include <cstdlib>
#include <functional>

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "SDK_PROVIDER_CHECK_FAILED line=%d %s\n", __LINE__, #condition); std::exit(1); } } while (false)

namespace {
const QString service = QStringLiteral("org.example.SailplayMedia");
const QString appPath = QStringLiteral("/org/sailplay/v1/App");
const QString appInterface = QStringLiteral("org.sailplay.App1");
const QString sessionInterface = QStringLiteral("org.sailplay.Session1");
const QString propertiesInterface = QStringLiteral("org.freedesktop.DBus.Properties");

bool waitFor(const std::function<bool()> &ready, int timeout = 2000)
{
    QElapsedTimer elapsed;
    elapsed.start();
    while (!ready() && elapsed.elapsed() < timeout) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(1);
    }
    return ready();
}

QDBusMessage call(const QDBusConnection &bus, const QString &path, const QString &interface,
                  const QString &member, const QVariantList &arguments = QVariantList())
{
    QDBusMessage message = QDBusMessage::createMethodCall(service, path, interface, member);
    message.setArguments(arguments);
    QDBusPendingCallWatcher watcher(bus.asyncCall(message, 2000));
    QEventLoop loop;
    QObject::connect(&watcher, &QDBusPendingCallWatcher::finished, &loop, &QEventLoop::quit);
    if (!watcher.isFinished()) loop.exec();
    return watcher.reply();
}

QString open(const QDBusConnection &bus, const QString &presentation = QStringLiteral("car"))
{
    const auto reply = call(bus, appPath, appInterface, QStringLiteral("OpenSession"),
        QVariantList() << presentation << (QStringList() << QStringLiteral("media")));
    CHECK(reply.type() == QDBusMessage::ReplyMessage && reply.arguments().size() == 1);
    return qvariant_cast<QDBusObjectPath>(reply.arguments().first()).path();
}

QStringList clientNames(const QDBusConnection &bus)
{
    return bus.interface()->registeredServiceNames().value().filter(QStringLiteral("org.sailplay.Client.c"));
}
}

class SignalProbe : public QObject
{
    Q_OBJECT
public:
    int states = 0;
    int properties = 0;
public slots:
    void StateChanged(qulonglong, const QVariantMap &) { ++states; }
    void PropertiesChanged(const QString &, const QVariantMap &, const QStringList &) { ++properties; }
};

int main(int argc, char **argv)
{
    QCoreApplication application(argc, argv);
    auto bus = QDBusConnection::sessionBus();
    CHECK(bus.isConnected());
    SailplayProvider invalid{QString(), QVariantMap()};
    CHECK(!invalid.start());
    SailplayProvider badState(QStringLiteral("fixture"), QVariantMap{{QString(), true}});
    CHECK(!badState.start());
    SailplayProvider provider(bus, QStringLiteral("fixture-media"), QVariantMap{{QStringLiteral("playing"), false}},
                              QStringList() << QStringLiteral("media"));
    CHECK(provider.start() && bus.registerService(service));
    CHECK(provider.revision() == 1);
    auto owner = QDBusConnection::connectToBus(QDBusConnection::SessionBus, QStringLiteral("sdk-provider-owner"));
    auto stranger = QDBusConnection::connectToBus(QDBusConnection::SessionBus, QStringLiteral("sdk-provider-stranger"));
    CHECK(owner.baseService() != stranger.baseService());
    const auto info = call(owner, appPath, propertiesInterface, QStringLiteral("GetAll"), QVariantList() << appInterface);
    CHECK(info.type() == QDBusMessage::ReplyMessage);
    const auto values = qdbus_cast<QVariantMap>(info.arguments().first());
    CHECK(values.value(QStringLiteral("ApiVersion")).toUInt() == 1);
    CHECK(values.value(QStringLiteral("InstanceId")).toString() == provider.instanceId());
    CHECK(qdbus_cast<QStringList>(values.value(QStringLiteral("Capabilities"))) ==
          (QStringList() << QStringLiteral("actions") << QStringLiteral("media") << QStringLiteral("state")));
    CHECK(call(owner, appPath, appInterface, QStringLiteral("OpenSession"),
        QVariantList() << QStringLiteral("screen") << QStringList()).errorName() == QStringLiteral("org.sailplay.Error1.NotSupported"));
    CHECK(call(owner, appPath, appInterface, QStringLiteral("OpenSession"),
        QVariantList() << QStringLiteral("car") << (QStringList() << QStringLiteral("navigation"))).errorName() == QStringLiteral("org.sailplay.Error1.NotSupported"));
    CHECK(call(owner, appPath, appInterface, QStringLiteral("OpenSession"),
        QVariantList() << QStringLiteral("car") << QStringLiteral("media")).errorName() == QStringLiteral("org.freedesktop.DBus.Error.InvalidArgs"));
    const QString car = open(owner);
    const QString phone = open(owner, QStringLiteral("phone"));
    CHECK(provider.sessionCount() == 2 && provider.activeSessionCount() == 2);
    CHECK(car.startsWith(appPath + QStringLiteral("/sessions/s")));
    CHECK(call(stranger, car, sessionInterface, QStringLiteral("GetSnapshot")).errorName() == QStringLiteral("org.sailplay.Error1.NotOwner"));
    CHECK(call(stranger, car, propertiesInterface, QStringLiteral("GetAll"), QVariantList() << sessionInterface).errorName() == QStringLiteral("org.sailplay.Error1.NotOwner"));
    CHECK(call(stranger, car, sessionInterface, QStringLiteral("Close")).errorName() == QStringLiteral("org.sailplay.Error1.NotOwner"));
    CHECK(call(stranger, car, sessionInterface, QStringLiteral("SetActive"), QVariantList() << false).errorName() == QStringLiteral("org.sailplay.Error1.NotOwner"));
    CHECK(call(owner, car, sessionInterface, QStringLiteral("GetSnapshot"), QVariantList() << true).errorName() == QStringLiteral("org.freedesktop.DBus.Error.InvalidArgs"));
    CHECK(call(owner, car, sessionInterface, QStringLiteral("Close"), QVariantList() << true).errorName() == QStringLiteral("org.freedesktop.DBus.Error.InvalidArgs"));
    CHECK(call(owner, car, propertiesInterface, QStringLiteral("Get"), QVariantList() << sessionInterface << QStringLiteral("Missing"))
        .errorName() == QStringLiteral("org.freedesktop.DBus.Error.UnknownProperty"));
    SignalProbe permitted, forbidden;
    CHECK(owner.connect(service, car, sessionInterface, QStringLiteral("StateChanged"), &permitted, SLOT(StateChanged(qulonglong,QVariantMap))));
    CHECK(stranger.connect(service, car, sessionInterface, QStringLiteral("StateChanged"), &forbidden, SLOT(StateChanged(qulonglong,QVariantMap))));
    CHECK(owner.connect(service, car, propertiesInterface, QStringLiteral("PropertiesChanged"), &permitted, SLOT(PropertiesChanged(QString,QVariantMap,QStringList))));
    CHECK(stranger.connect(service, car, propertiesInterface, QStringLiteral("PropertiesChanged"), &forbidden, SLOT(PropertiesChanged(QString,QVariantMap,QStringList))));
    CHECK(provider.publish(QVariantMap{{QStringLiteral("playing"), false}}) && provider.revision() == 1);
    CHECK(!provider.publish(QVariantMap{{QString(), true}}) && provider.revision() == 1);
    CHECK(!provider.publish(QVariantMap{{QStringLiteral("empty"), QVariant()}}) && provider.revision() == 1);
    CHECK(!provider.publish(QVariantMap{{QStringLiteral("nested"), QVariantHash{{QStringLiteral("empty"), QVariant()}}}}) && provider.revision() == 1);
    {
        const QString hashPath = QStringLiteral("/org/sailplay/hash/App");
        SailplayProvider hashProvider(bus, QStringLiteral("fixture-hash"),
            QVariantMap{{QStringLiteral("nested"), QVariantHash{{QStringLiteral("value"), 1}}}});
        CHECK(hashProvider.start(hashPath));
        const auto opened = call(owner, hashPath, appInterface, QStringLiteral("OpenSession"),
            QVariantList() << QStringLiteral("car") << QStringList());
        CHECK(opened.type() == QDBusMessage::ReplyMessage);
        const QString path = qvariant_cast<QDBusObjectPath>(opened.arguments().first()).path();
        const auto saved = call(owner, path, sessionInterface, QStringLiteral("GetSnapshot"));
        CHECK(saved.type() == QDBusMessage::ReplyMessage);
        const auto state = qdbus_cast<QVariantMap>(saved.arguments().at(1));
        CHECK(qdbus_cast<QVariantMap>(state.value(QStringLiteral("nested"))).value(QStringLiteral("value")).toInt() == 1);
    }
    CHECK(provider.publish(QVariantMap{{QStringLiteral("playing"), true}}) && provider.revision() == 2);
    CHECK(waitFor([&]() { return permitted.states == 1; }));
    CHECK(forbidden.states == 0);
    const auto snapshot = call(owner, car, sessionInterface, QStringLiteral("GetSnapshot"));
    CHECK(snapshot.type() == QDBusMessage::ReplyMessage && snapshot.signature() == QStringLiteral("ta{sv}"));
    CHECK(snapshot.arguments().first().toULongLong() == 2);
    CHECK(qdbus_cast<QVariantMap>(snapshot.arguments().at(1)).value(QStringLiteral("playing")).toBool());
    CHECK(call(owner, car, sessionInterface, QStringLiteral("SetActive"), QVariantList() << false).type() == QDBusMessage::ReplyMessage);
    CHECK(provider.sessionCount() == 2 && provider.activeSessionCount() == 1);
    CHECK(waitFor([&]() { return permitted.properties == 1; }));
    CHECK(forbidden.properties == 0);
    CHECK(call(owner, car, sessionInterface, QStringLiteral("SetActive"), QVariantList() << 1).errorName() == QStringLiteral("org.freedesktop.DBus.Error.InvalidArgs"));
    CHECK(call(owner, car, sessionInterface, QStringLiteral("Invoke"),
        QVariantList() << QVariant::fromValue(qulonglong(1)) << QStringLiteral("play") << QVariantMap() << QVariant::fromValue(qulonglong(0)))
        .errorName() == QStringLiteral("org.sailplay.Error1.NotSupported"));
    CHECK(call(owner, phone, sessionInterface, QStringLiteral("Close")).type() == QDBusMessage::ReplyMessage);
    CHECK(provider.sessionCount() == 1);
    CHECK(call(owner, phone, sessionInterface, QStringLiteral("GetSnapshot")).errorName() == QStringLiteral("org.sailplay.Error1.InvalidSession"));
    {
        const auto ephemeral = QDBusConnection::connectToBus(QDBusConnection::SessionBus, QStringLiteral("sdk-provider-ephemeral"));
        open(ephemeral);
        CHECK(provider.sessionCount() == 2);
    }
    QDBusConnection::disconnectFromBus(QStringLiteral("sdk-provider-ephemeral"));
    CHECK(waitFor([&]() { return provider.sessionCount() == 1; }));
    QStringList remaining;
    remaining << car;
    for (int count = 1; count < 64; ++count) remaining << open(owner);
    CHECK(provider.sessionCount() == 64);
    CHECK(call(owner, appPath, appInterface, QStringLiteral("OpenSession"), QVariantList() << QStringLiteral("car") << QStringList())
        .errorName() == QStringLiteral("org.sailplay.Error1.LimitExceeded"));
    for (const QString &path : remaining) CHECK(call(owner, path, sessionInterface, QStringLiteral("Close")).type() == QDBusMessage::ReplyMessage);
    CHECK(provider.sessionCount() == 0);
    int abandonedChanges = 0;
    const auto abandonedConnection = QObject::connect(&provider, &SailplayProvider::sessionsChanged,
        [&]() { ++abandonedChanges; });
    {
        auto vanished = QDBusConnection::connectToBus(QDBusConnection::SessionBus, QStringLiteral("sdk-provider-vanished"));
        auto message = QDBusMessage::createMethodCall(service, appPath, appInterface, QStringLiteral("OpenSession"));
        message.setArguments(QVariantList() << QStringLiteral("car") << QStringList());
        CHECK(vanished.send(message));
        CHECK(vanished.interface()->isServiceRegistered(vanished.baseService()).value());
    }
    QDBusConnection::disconnectFromBus(QStringLiteral("sdk-provider-vanished"));
    CHECK(waitFor([&]() { return abandonedChanges > 0; }));
    CHECK(provider.sessionCount() == 0);
    QObject::disconnect(abandonedConnection);
    const auto originalNames = clientNames(bus);
    {
        SailplaySession first(owner), second(owner);
        first.open(service, appPath, QStringLiteral("car"), QStringList() << QStringLiteral("media"));
        CHECK(clientNames(bus).size() == originalNames.size() + 1);
        const auto firstNames = clientNames(bus);
        second.open(service, appPath, QStringLiteral("phone"));
        CHECK(clientNames(bus).size() == originalNames.size() + 2);
        CHECK(waitFor([&]() { return first.ready() && second.ready(); }));
        CHECK(provider.sessionCount() == 2);
        second.close();
        second.close();
        CHECK(clientNames(bus) == firstNames);
        first.open(service, appPath);
        CHECK(clientNames(bus).size() == originalNames.size() + 1);
        CHECK(waitFor([&]() { return first.ready() && provider.sessionCount() == 1; }));
    }
    CHECK(clientNames(bus) == originalNames);
    CHECK(waitFor([&]() { return provider.sessionCount() == 0; }));
    {
        SailplaySession unavailable{QDBusConnection(QStringLiteral("sdk-client-unconnected"))};
        int failures = 0;
        QObject::connect(&unavailable, &SailplaySession::errorOccurred, [&]() { ++failures; });
        unavailable.open(service, appPath);
        CHECK(failures == 1 && clientNames(bus) == originalNames && provider.sessionCount() == 0);
    }
    QTemporaryDir temporary;
    CHECK(temporary.isValid());
    QFile desktop(temporary.path() + QStringLiteral("/media.desktop"));
    CHECK(desktop.open(QIODevice::WriteOnly));
    desktop.write("[Desktop Entry]\nType=Application\nX-Sailplay-ApiVersion=1\nX-Sailplay-Service=org.example.SailplayMedia\nX-Sailplay-Capabilities=media;\n");
    desktop.close();
    const SailplayApplication declaration = SailplayApplication::fromDesktopFile(desktop.fileName());
    CHECK(declaration.mediaTemplate() && !declaration.navigationTemplate());
    SailplayMusicHost music;
    int errors = 0;
    QObject::connect(&music, &SailplayMusicHost::errorOccurred, [&]() { ++errors; });
    music.setActive(false);
    music.open(declaration);
    CHECK(waitFor([&]() { return provider.sessionCount() == 1 && provider.activeSessionCount() == 0; }));
    CHECK(errors == 0);
    music.open(declaration);
    CHECK(provider.sessionCount() == 1);
    music.setActive(true);
    CHECK(waitFor([&]() { return provider.activeSessionCount() == 1; }));
    music.setActive(false);
    CHECK(waitFor([&]() { return provider.activeSessionCount() == 0; }));
    CHECK(provider.sessionCount() == 1);
    SailplayApplication replacement = declaration;
    replacement.service = QStringLiteral("org.example.SailplayReplacement");
    auto firstBus = QDBusConnection::connectToBus(QDBusConnection::SessionBus, QStringLiteral("sdk-provider-first-backend"));
    SailplayProvider first(firstBus, QStringLiteral("replacement"), QVariantMap{{QStringLiteral("value"), 1}}, QStringList() << QStringLiteral("media"));
    CHECK(first.start() && firstBus.registerService(replacement.service));
    music.open(replacement);
    CHECK(waitFor([&]() { return provider.sessionCount() == 0 && first.sessionCount() == 1; }));
    const auto reconnectNames = clientNames(bus);
    first.close();
    firstBus.unregisterService(replacement.service);
    waitFor([&]() { return false; }, 30);
    auto secondBus = QDBusConnection::connectToBus(QDBusConnection::SessionBus, QStringLiteral("sdk-provider-second-backend"));
    SailplayProvider second(secondBus, QStringLiteral("replacement"), QVariantMap{{QStringLiteral("value"), 2}}, QStringList() << QStringLiteral("media"));
    CHECK(second.start() && secondBus.registerService(replacement.service));
    CHECK(first.instanceId() != second.instanceId());
    CHECK(waitFor([&]() { return second.sessionCount() == 1; }));
    CHECK(clientNames(bus) == reconnectNames);
    music.open(replacement);
    CHECK(second.sessionCount() == 1);
    music.close();
    CHECK(waitFor([&]() { return second.sessionCount() == 0; }));
    music.open(declaration);
    CHECK(waitFor([&]() { return provider.sessionCount() == 1 && provider.activeSessionCount() == 0; }));
    music.close();
    CHECK(waitFor([&]() { return provider.sessionCount() == 0; }));
    CHECK(errors == 0);
    CHECK(clientNames(bus) == originalNames);
    puts("QT_SDK_PROVIDER_PASS canonical-signatures caller-ownership directed-signals hidden-leases owner-loss limits media-host activity backend-replacement teardown");
    return 0;
}

#include "sdk_provider_test.moc"
