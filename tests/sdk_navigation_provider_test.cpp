#include "sailplayprovider.h"

#include <QCoreApplication>
#include <QDBusArgument>
#include <QDBusConnectionInterface>
#include <QDBusPendingCallWatcher>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QThread>
#include <QVector>

#include <cstdio>
#include <cstdlib>
#include <functional>
#include <limits>
#include <stdexcept>

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "SDK_NAVIGATION_CHECK_FAILED line=%d %s\n", __LINE__, #condition); std::exit(1); } } while (false)

namespace {
const QString service = QStringLiteral("org.example.SailplayNativeNavigation");
const QString appPath = QStringLiteral("/org/sailplay/v1/App");
const QString appInterface = QStringLiteral("org.sailplay.App1");
const QString sessionInterface = QStringLiteral("org.sailplay.Session1");
const QString navigationInterface = QStringLiteral("org.sailplay.Navigation1");
const QString errorPrefix = QStringLiteral("org.sailplay.Error1.");

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

QString open(const QDBusConnection &bus, const QString &presentation)
{
    const auto reply = call(bus, appPath, appInterface, QStringLiteral("OpenSession"),
        QVariantList() << presentation << (QStringList() << QStringLiteral("navigation")));
    CHECK(reply.type() == QDBusMessage::ReplyMessage);
    return qvariant_cast<QDBusObjectPath>(reply.arguments().first()).path();
}

QDBusMessage invoke(const QDBusConnection &bus, const QString &path, qulonglong request,
                    const QString &action, qulonglong revision = 0,
                    const QVariantMap &parameters = QVariantMap())
{
    return call(bus, path, sessionInterface, QStringLiteral("Invoke"),
        QVariantList() << QVariant::fromValue(request) << action << parameters << QVariant::fromValue(revision));
}
}

class SignalProbe : public QObject
{
    Q_OBJECT
public:
    int states = 0;
    int guidance = 0;
    int completions = 0;
    qulonglong request = 0;
    qulonglong revision = 0;
    QVariantMap result;
    QString error;
public slots:
    void StateChanged(qulonglong, const QVariantMap &) { ++states; }
    void GuidanceChanged(qulonglong, const QVariantMap &) { ++guidance; }
    void RequestFinished(qulonglong id, qulonglong stateRevision, const QVariantMap &value,
                         const QString &errorName, const QString &) {
        ++completions;
        request = id;
        revision = stateRevision;
        result = value;
        error = errorName;
    }
};

int main(int argc, char **argv)
{
    QCoreApplication application(argc, argv);
    auto bus = QDBusConnection::sessionBus();
    CHECK(bus.isConnected());
    const QStringList navigationCapability = {QStringLiteral("navigation")};
    const QVariantMap idle = SailplayProvider::navigationGuidance();
    SailplayProvider missing(QStringLiteral("missing-guidance"), QVariantMap(), navigationCapability);
    CHECK(!missing.start());
    SailplayProvider noStop(QStringLiteral("missing-stop"), {{QStringLiteral("navigation"), idle}}, navigationCapability);
    CHECK(!noStop.start());
    SailplayProvider provider(QStringLiteral("native-map"), {{QStringLiteral("navigation"), idle}}, navigationCapability);
    QVector<qulonglong> pending;
    provider.setActionHandler(QStringLiteral("navigation.stop"), [&](qulonglong id, const QVariantMap &) { pending << id; });
    provider.setActionHandler(QStringLiteral("throw"), [](qulonglong, const QVariantMap &) { throw std::runtime_error("action failure"); });
    CHECK(provider.start() && bus.registerService(service));
    auto owner = QDBusConnection::connectToBus(QDBusConnection::SessionBus, QStringLiteral("native-navigation-owner"));
    auto stranger = QDBusConnection::connectToBus(QDBusConnection::SessionBus, QStringLiteral("native-navigation-stranger"));
    const QString car = open(owner, QStringLiteral("car"));
    const QString phone = open(owner, QStringLiteral("phone"));
    CHECK(provider.introspect(car).contains(navigationInterface));
    CHECK(call(stranger, car, navigationInterface, QStringLiteral("GetGuidance")).errorName() == errorPrefix + QStringLiteral("NotOwner"));
    CHECK(call(owner, car, navigationInterface, QStringLiteral("GetGuidance"), QVariantList() << true).errorName()
        == QStringLiteral("org.freedesktop.DBus.Error.InvalidArgs"));
    const auto initial = call(owner, car, navigationInterface, QStringLiteral("GetGuidance"));
    CHECK(initial.type() == QDBusMessage::ReplyMessage && initial.signature() == QStringLiteral("ta{sv}"));
    CHECK(qdbus_cast<QVariantMap>(initial.arguments().at(1)) == idle);
    SignalProbe permitted, forbidden;
    for (auto connection : {owner, stranger}) {
        SignalProbe *probe = connection.baseService() == owner.baseService() ? &permitted : &forbidden;
        CHECK(connection.connect(service, car, sessionInterface, QStringLiteral("StateChanged"), probe, SLOT(StateChanged(qulonglong,QVariantMap))));
        CHECK(connection.connect(service, car, navigationInterface, QStringLiteral("GuidanceChanged"), probe, SLOT(GuidanceChanged(qulonglong,QVariantMap))));
        CHECK(connection.connect(service, car, sessionInterface, QStringLiteral("RequestFinished"), probe,
            SLOT(RequestFinished(qulonglong,qulonglong,QVariantMap,QString,QString))));
    }
    QVariantMap active = SailplayProvider::navigationGuidance(QStringLiteral("active"));
    active[QStringLiteral("maneuver")] = QStringLiteral("turn-right");
    active[QStringLiteral("currentRoad")] = QString::fromUtf8("道路 🌍");
    active[QStringLiteral("remainingSeconds")] = std::numeric_limits<qulonglong>::max();
    CHECK(provider.publish({{QStringLiteral("navigation"), active}}));
    CHECK(waitFor([&] { return permitted.guidance == 1 && permitted.states == 1; }));
    CHECK(forbidden.guidance == 0 && forbidden.states == 0);
    const auto saved = call(owner, car, sessionInterface, QStringLiteral("GetSnapshot"));
    CHECK(qdbus_cast<QVariantMap>(qdbus_cast<QVariantMap>(saved.arguments().at(1)).value(QStringLiteral("navigation"))) == active);
    for (const auto &key : idle.keys()) {
        QVariantMap invalid = active;
        invalid.remove(key);
        CHECK(!provider.publish({{QStringLiteral("navigation"), invalid}}));
    }
    const QVariantMap badFields = {{QStringLiteral("mode"), QStringLiteral("bus")},
        {QStringLiteral("maneuver"), QStringLiteral("right")}, {QStringLiteral("state"), QStringLiteral("running")},
        {QStringLiteral("drivingSide"), QStringLiteral("center")}, {QStringLiteral("exitNumber"), 1},
        {QStringLiteral("remainingSeconds"), 1}, {QStringLiteral("updatedMs"), std::numeric_limits<qulonglong>::max()},
        {QStringLiteral("nextDistanceMeters"), -1.0}, {QStringLiteral("remainingDistanceMeters"), std::numeric_limits<double>::infinity()},
        {QStringLiteral("currentRoad"), QString(1025, QLatin1Char('x'))}, {QStringLiteral("nextRoad"), QString(QChar::Null)}};
    for (auto field = badFields.cbegin(); field != badFields.cend(); ++field) {
        QVariantMap invalid = active;
        invalid[field.key()] = field.value();
        CHECK(!provider.publish({{QStringLiteral("navigation"), invalid}}));
    }
    CHECK(provider.revision() == 2);
    CHECK(invoke(stranger, car, 1, QStringLiteral("navigation.stop")).errorName() == errorPrefix + QStringLiteral("NotOwner"));
    CHECK(invoke(owner, car, 0, QStringLiteral("navigation.stop")).errorName() == errorPrefix + QStringLiteral("InvalidArgument"));
    CHECK(invoke(owner, car, 1, QStringLiteral("navigation.stop"), 1).errorName() == errorPrefix + QStringLiteral("StaleRevision"));
    CHECK(invoke(owner, car, 1, QStringLiteral("unknown")).errorName() == errorPrefix + QStringLiteral("NotSupported"));
    CHECK(invoke(owner, car, 1, QStringLiteral("navigation.stop"), 2).type() == QDBusMessage::ReplyMessage);
    CHECK(waitFor([&] { return pending.size() == 1; }));
    CHECK(provider.pendingCount() == 1);
    CHECK(invoke(owner, car, 1, QStringLiteral("navigation.stop")).errorName() == errorPrefix + QStringLiteral("DuplicateRequest"));
    CHECK(!provider.complete(pending.first(), {{QStringLiteral("invalid"), QVariant()}}));
    CHECK(provider.pendingCount() == 1);
    const QVariantMap stopped = {{QStringLiteral("navigation"), SailplayProvider::navigationGuidance(QStringLiteral("stopped"))}};
    CHECK(provider.complete(pending.takeFirst(), {{QStringLiteral("stopped"), true}}, stopped));
    CHECK(waitFor([&] { return permitted.completions == 1; }));
    CHECK(permitted.request == 1 && permitted.revision == 3 && permitted.error.isEmpty());
    CHECK(permitted.result.value(QStringLiteral("stopped")).toBool());
    CHECK(provider.pendingCount() == 0 && forbidden.completions == 0);
    CHECK(invoke(owner, car, 2, QStringLiteral("navigation.stop"), 3).type() == QDBusMessage::ReplyMessage);
    CHECK(waitFor([&] { return pending.size() == 1; }));
    CHECK(provider.publish({{QStringLiteral("navigation"), active}}));
    CHECK(provider.complete(pending.takeFirst(), QVariantMap(), stopped));
    CHECK(waitFor([&] { return permitted.completions == 2; }));
    CHECK(permitted.error == errorPrefix + QStringLiteral("StaleRevision") && provider.revision() == 4);
    CHECK(invoke(owner, car, 3, QStringLiteral("throw")).type() == QDBusMessage::ReplyMessage);
    CHECK(waitFor([&] { return permitted.completions == 3; }));
    CHECK(permitted.error == errorPrefix + QStringLiteral("Failed") && provider.pendingCount() == 0);
    CHECK(call(owner, car, sessionInterface, QStringLiteral("SetActive"), QVariantList() << false).type() == QDBusMessage::ReplyMessage);
    CHECK(call(owner, phone, sessionInterface, QStringLiteral("Close")).type() == QDBusMessage::ReplyMessage);
    CHECK(provider.sessionCount() == 1 && provider.activeSessionCount() == 0);
    for (qulonglong id = 4; id < 68; ++id)
        CHECK(invoke(owner, car, id, QStringLiteral("navigation.stop")).type() == QDBusMessage::ReplyMessage);
    CHECK(waitFor([&] { return pending.size() == 64; }));
    CHECK(provider.pendingCount() == 64);
    CHECK(invoke(owner, car, 68, QStringLiteral("navigation.stop")).errorName() == errorPrefix + QStringLiteral("LimitExceeded"));
    CHECK(call(owner, car, sessionInterface, QStringLiteral("Close")).type() == QDBusMessage::ReplyMessage);
    CHECK(provider.sessionCount() == 0 && provider.pendingCount() == 64);
    CHECK(provider.complete(pending.takeFirst(), {{QStringLiteral("orphanCompleted"), true}}, stopped));
    CHECK(provider.revision() == 5);
    for (qulonglong id : pending) CHECK(provider.complete(id));
    pending.clear();
    CHECK(provider.pendingCount() == 0);
    waitFor([] { return false; }, 20);
    CHECK(permitted.completions == 3 && forbidden.completions == 0);
    {
        auto lost = QDBusConnection::connectToBus(QDBusConnection::SessionBus, QStringLiteral("native-navigation-lost"));
        const QString path = open(lost, QStringLiteral("car"));
        CHECK(invoke(lost, path, 1, QStringLiteral("navigation.stop")).type() == QDBusMessage::ReplyMessage);
        CHECK(waitFor([&] { return pending.size() == 1; }));
    }
    QDBusConnection::disconnectFromBus(QStringLiteral("native-navigation-lost"));
    CHECK(waitFor([&] { return provider.sessionCount() == 0; }));
    CHECK(provider.pendingCount() == 1 && provider.complete(pending.takeFirst()));
    CHECK(provider.pendingCount() == 0);
    CHECK(call(owner, car, navigationInterface, QStringLiteral("GetGuidance")).errorName() == errorPrefix + QStringLiteral("InvalidSession"));
    puts("QT_NATIVE_NAVIGATION_PROVIDER_PASS typed-guidance ownership directed-signals async-actions revision-conflicts limits closed-view-work vanished-caller");
    return 0;
}

#include "sdk_navigation_provider_test.moc"
