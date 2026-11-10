#include "sailplayprovider.h"

#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusArgument>
#include <QDBusMessage>
#include <QDBusMetaType>
#include <QDBusObjectPath>
#include <QDBusServiceWatcher>
#include <QDBusVariant>
#include <QFile>
#include <QThread>
#include <QTimer>
#include <QUuid>
#include <QVector>
#include <QXmlStreamReader>
#include <cmath>
#include <exception>
#include <limits>
#include <time.h>

static void initializeSailplayContracts()
{
    Q_INIT_RESOURCE(qmake_sailplay_contracts);
}

namespace {
const QString appInterface = QStringLiteral("org.sailplay.App1");
const QString sessionInterface = QStringLiteral("org.sailplay.Session1");
const QString navigationInterface = QStringLiteral("org.sailplay.Navigation1");
const QString propertiesInterface = QStringLiteral("org.freedesktop.DBus.Properties");
const QString errorPrefix = QStringLiteral("org.sailplay.Error1.");

bool errorReply(const QDBusMessage &message, const QDBusConnection &connection,
                const QString &name, const QString &description)
{
    connection.send(message.createErrorReply(name, description));
    return true;
}

QString uniqueToken()
{
    return QString::fromLatin1(QUuid::createUuid().toRfc4122().toHex());
}

bool validString(const QString &value)
{
    return !value.isEmpty() && !value.contains(QChar::Null);
}

qulonglong boottimeMs()
{
    timespec now = {};
    clock_gettime(CLOCK_BOOTTIME, &now);
    return qulonglong(now.tv_sec) * 1000 + now.tv_nsec / 1000000;
}
}

SailplayProvider::SailplayProvider(const QString &applicationId, const QVariantMap &state,
                                 const QStringList &capabilities, QObject *parent)
    : SailplayProvider(QDBusConnection::sessionBus(), applicationId, state, capabilities, parent)
{
}

SailplayProvider::SailplayProvider(const QDBusConnection &bus, const QString &applicationId,
                                 const QVariantMap &state, const QStringList &capabilities,
                                 QObject *parent)
    : QDBusVirtualObject(parent), m_bus(bus),
      m_watcher(new QDBusServiceWatcher(QString(), bus, QDBusServiceWatcher::WatchForUnregistration, this)),
      m_applicationId(applicationId), m_instanceId(uniqueToken()), m_capabilities(capabilities), m_state(state)
{
    initializeSailplayContracts();
    m_appContract = readContract(appInterface);
    m_sessionContract = readContract(sessionInterface);
    m_navigation = capabilities.contains(QStringLiteral("navigation"));
    if (m_navigation) m_navigationContract = readContract(navigationInterface);
    m_valid = validString(applicationId) && validState(state)
        && !m_appContract.xml.isEmpty() && !m_sessionContract.xml.isEmpty()
        && (!m_navigation || (!m_navigationContract.xml.isEmpty()
            && validGuidance(state.value(QStringLiteral("navigation")).toMap())));
    for (const QString &capability : capabilities) m_valid = m_valid && validString(capability);
    m_capabilities << QStringLiteral("state") << QStringLiteral("actions");
    m_capabilities.removeDuplicates();
    m_capabilities.sort();
    connect(m_watcher, &QDBusServiceWatcher::serviceUnregistered, this, &SailplayProvider::ownerLost);
}

void SailplayProvider::ownerLost(const QString &owner)
{
    bool changed = false;
    for (const QString &path : m_sessions.keys()) {
        if (m_sessions.value(path).owner == owner) {
            m_sessions.remove(path);
            changed = true;
        }
    }
    m_watcher->removeWatchedService(owner);
    if (changed) emit sessionsChanged();
}

SailplayProvider::~SailplayProvider()
{
    close();
}

SailplayProvider::Contract SailplayProvider::readContract(const QString &interface)
{
    QFile source(QStringLiteral(":/sailplay-sdk/interfaces/") + interface + QStringLiteral(".xml"));
    if (!source.open(QIODevice::ReadOnly)) return Contract();
    const QString xml = QString::fromUtf8(source.readAll());
    QXmlStreamReader reader(xml);
    Contract result;
    QString method;
    while (!reader.atEnd()) {
        reader.readNext();
        if (reader.isStartElement() && reader.name() == QStringLiteral("method")) {
            method = reader.attributes().value(QStringLiteral("name")).toString();
            result.methods.insert(method, QString());
        } else if (reader.isStartElement() && reader.name() == QStringLiteral("arg") && !method.isEmpty()
                   && reader.attributes().value(QStringLiteral("direction")) == QStringLiteral("in")) {
            result.methods[method] += reader.attributes().value(QStringLiteral("type")).toString();
        } else if (reader.isEndElement() && reader.name() == QStringLiteral("method")) {
            method.clear();
        }
    }
    const int first = xml.indexOf(QStringLiteral("<interface "));
    const int last = xml.indexOf(QStringLiteral("</interface>"), first);
    if (reader.hasError() || first < 0 || last < 0) return Contract();
    result.xml = xml.mid(first, last + 12 - first);
    return result;
}

bool SailplayProvider::validState(const QVariantMap &state)
{
    for (auto item = state.cbegin(); item != state.cend(); ++item) {
        if (!validString(item.key()) || !validValue(item.value())) return false;
    }
    return true;
}

bool SailplayProvider::validValue(const QVariant &value, int depth)
{
    if (!value.isValid() || depth > 32) return false;
    if (value.type() == QVariant::String) return !value.toString().contains(QChar::Null);
    if (value.type() == QVariant::StringList) {
        for (const QString &item : value.toStringList()) {
            if (item.contains(QChar::Null)) return false;
        }
    } else if (value.type() == QVariant::Map) {
        const QVariantMap map = value.toMap();
        for (auto item = map.cbegin(); item != map.cend(); ++item) {
            if (item.key().contains(QChar::Null) || !validValue(item.value(), depth + 1)) return false;
        }
    } else if (value.type() == QVariant::Hash) {
        const QVariantHash hash = value.toHash();
        for (auto item = hash.cbegin(); item != hash.cend(); ++item) {
            if (item.key().contains(QChar::Null) || !validValue(item.value(), depth + 1)) return false;
        }
    } else if (value.type() == QVariant::List) {
        for (const QVariant &item : value.toList()) {
            if (!validValue(item, depth + 1)) return false;
        }
    } else if (value.userType() == qMetaTypeId<QDBusVariant>()) {
        return validValue(qvariant_cast<QDBusVariant>(value).variant(), depth + 1);
    }
    // Qt 5.6 can marshal values while resolving a container's signature.
    // Reject invalid nested variants before querying that signature.
    return QDBusMetaType::typeToSignature(value.userType()) != nullptr;
}

bool SailplayProvider::start(const QString &path)
{
    if (!m_path.isEmpty()) return path == m_path;
    if (!m_valid || (m_navigation && !m_actions.contains(QStringLiteral("navigation.stop")))
        || !m_bus.isConnected() || !path.startsWith(QLatin1Char('/'))
        || !m_bus.registerVirtualObject(path, this, QDBusConnection::SubPath)) return false;
    m_path = path;
    return true;
}

void SailplayProvider::close()
{
    if (m_path.isEmpty()) return;
    m_bus.unregisterObject(m_path, QDBusConnection::UnregisterTree);
    m_path.clear();
    m_watcher->setWatchedServices(QStringList());
    const bool hadSessions = !m_sessions.isEmpty();
    m_sessions.clear();
    const bool hadPending = !m_pending.isEmpty();
    m_pending.clear();
    if (hadSessions) emit sessionsChanged();
    if (hadPending) emit pendingChanged();
}

int SailplayProvider::activeSessionCount() const
{
    int count = 0;
    for (const Session &session : m_sessions) count += session.active;
    return count;
}

QString SailplayProvider::introspect(const QString &path) const
{
    if (path == m_path) return m_appContract.xml;
    if (m_sessions.contains(path)) return m_sessionContract.xml + m_navigationContract.xml;
    return QString();
}

bool SailplayProvider::properties(const QDBusMessage &message, const QDBusConnection &connection,
                                  const QString &interface, const QVariantMap &values)
{
    const QVariantList arguments = message.arguments();
    const QString member = message.member();
    const QString signature = member == QStringLiteral("GetAll") ? QStringLiteral("s")
        : member == QStringLiteral("Get") ? QStringLiteral("ss") : QStringLiteral("ssv");
    if (member != QStringLiteral("GetAll") && member != QStringLiteral("Get") && member != QStringLiteral("Set"))
        return errorReply(message, connection, QStringLiteral("org.freedesktop.DBus.Error.UnknownMethod"),
                          QStringLiteral("Unknown property method"));
    if (message.signature() != signature)
        return errorReply(message, connection, QStringLiteral("org.freedesktop.DBus.Error.InvalidArgs"),
                          QStringLiteral("Property arguments do not match the D-Bus contract"));
    if (arguments.first().toString() != interface)
        return errorReply(message, connection, QStringLiteral("org.freedesktop.DBus.Error.UnknownInterface"),
                          QStringLiteral("Unknown property interface"));
    if (member == QStringLiteral("GetAll")) {
        connection.send(message.createReply(QVariantList() << values));
        return true;
    }
    const QString property = arguments.at(1).toString();
    if (!values.contains(property))
        return errorReply(message, connection, QStringLiteral("org.freedesktop.DBus.Error.UnknownProperty"),
                          QStringLiteral("Unknown property"));
    if (member == QStringLiteral("Set"))
        return errorReply(message, connection, QStringLiteral("org.freedesktop.DBus.Error.PropertyReadOnly"),
                          QStringLiteral("SDK properties are read-only"));
    connection.send(message.createReply(QVariantList() << QVariant::fromValue(QDBusVariant(values.value(property)))));
    return true;
}

bool SailplayProvider::handleMessage(const QDBusMessage &message, const QDBusConnection &connection)
{
    if (message.type() != QDBusMessage::MethodCallMessage || m_path.isEmpty()) return false;
    const bool app = message.path() == m_path;
    if (!app) {
        if (!m_sessions.contains(message.path()))
            return errorReply(message, connection, errorPrefix + QStringLiteral("InvalidSession"),
                              QStringLiteral("Presentation session has closed"));
        if (m_sessions.value(message.path()).owner != message.service())
            return errorReply(message, connection, errorPrefix + QStringLiteral("NotOwner"),
                              QStringLiteral("Presentation session belongs to another caller"));
    }
    const QString interface = app ? appInterface : sessionInterface;
    if (message.interface() == propertiesInterface) {
        const Session session = m_sessions.value(message.path());
        const QVariantMap values = app ? QVariantMap{
            {QStringLiteral("ApiVersion"), uint(1)}, {QStringLiteral("ApplicationId"), m_applicationId},
            {QStringLiteral("InstanceId"), m_instanceId}, {QStringLiteral("Capabilities"), m_capabilities}}
            : QVariantMap{{QStringLiteral("Presentation"), session.presentation}, {QStringLiteral("Active"), session.active}};
        return properties(message, connection, interface, values);
    }
    if (!app && m_navigation && message.interface() == navigationInterface) {
        if (message.member() != QStringLiteral("GetGuidance")) return false;
        if (message.signature() != m_navigationContract.methods.value(message.member()))
            return errorReply(message, connection, QStringLiteral("org.freedesktop.DBus.Error.InvalidArgs"),
                              QStringLiteral("Method arguments do not match the SDK XML"));
        connection.send(message.createReply(QVariantList() << QVariant::fromValue(m_revision)
            << m_state.value(QStringLiteral("navigation")).toMap()));
        return true;
    }
    if (message.interface() != interface) return false;
    const Contract &contract = app ? m_appContract : m_sessionContract;
    if (!contract.methods.contains(message.member())) return false;
    if (message.signature() != contract.methods.value(message.member()))
        return errorReply(message, connection, QStringLiteral("org.freedesktop.DBus.Error.InvalidArgs"),
                          QStringLiteral("Method arguments do not match the SDK XML"));
    const QVariantList arguments = message.arguments();
    if (app) {
        const QString presentation = arguments.first().toString();
        if (presentation != QStringLiteral("phone") && presentation != QStringLiteral("car"))
            return errorReply(message, connection, errorPrefix + QStringLiteral("NotSupported"),
                              QStringLiteral("Presentation must be phone or car"));
        const QStringList required = qdbus_cast<QStringList>(arguments.at(1));
        for (const QString &capability : required) {
            if (!m_capabilities.contains(capability))
                return errorReply(message, connection, errorPrefix + QStringLiteral("NotSupported"),
                                  QStringLiteral("A required capability is unavailable"));
        }
        if (!message.service().startsWith(QLatin1Char(':')))
            return errorReply(message, connection, errorPrefix + QStringLiteral("InvalidArgument"),
                              QStringLiteral("A unique D-Bus caller is required"));
        if (m_sessions.size() >= 64)
            return errorReply(message, connection, errorPrefix + QStringLiteral("LimitExceeded"),
                              QStringLiteral("Application presentation session limit reached"));
        const QString path = m_path + QStringLiteral("/sessions/s") + uniqueToken();
        Session session;
        session.owner = message.service();
        session.presentation = presentation;
        m_sessions.insert(path, session);
        m_watcher->addWatchedService(message.service());
        // A caller can disconnect after sending OpenSession but before its
        // unique-name watch is installed. Check liveness after installing the
        // watch and record so that either the query or owner loss releases it.
        QDBusConnectionInterface *daemon = m_bus.interface();
        if (!daemon || !daemon->isServiceRegistered(message.service()).value() || !m_sessions.contains(path)) {
            ownerLost(message.service());
            return errorReply(message, connection, errorPrefix + QStringLiteral("Disconnected"),
                              QStringLiteral("Presentation caller has disconnected"));
        }
        connection.send(message.createReply(QVariantList() << QVariant::fromValue(QDBusObjectPath(path))));
        emit sessionsChanged();
        return true;
    }
    if (message.member() == QStringLiteral("Invoke"))
        return invoke(message, connection);
    if (message.member() == QStringLiteral("GetSnapshot")) {
        connection.send(message.createReply(QVariantList() << QVariant::fromValue(m_revision) << m_state));
        return true;
    }
    if (message.member() == QStringLiteral("SetActive")) {
        Session &session = m_sessions[message.path()];
        const bool active = arguments.first().toBool();
        if (session.active != active) {
            session.active = active;
            sendSignal(message.path(), session, propertiesInterface, QStringLiteral("PropertiesChanged"),
                QVariantList() << sessionInterface << QVariantMap{{QStringLiteral("Active"), active}} << QStringList());
            emit sessionsChanged();
        }
    } else if (message.member() == QStringLiteral("Close")) {
        m_sessions.remove(message.path());
        bool watched = false;
        for (const Session &session : m_sessions) watched = watched || session.owner == message.service();
        if (!watched) m_watcher->removeWatchedService(message.service());
        emit sessionsChanged();
    }
    connection.send(message.createReply());
    return true;
}

void SailplayProvider::sendSignal(const QString &path, const Session &session, const QString &interface,
                                 const QString &member, const QVariantList &arguments)
{
    QDBusMessage signal = QDBusMessage::createTargetedSignal(session.owner, path, interface, member);
    signal.setArguments(arguments);
    m_bus.send(signal);
}

bool SailplayProvider::publish(const QVariantMap &state)
{
    if (QThread::currentThread() != thread() || !validState(state) || !m_valid
        || (m_navigation && !validGuidance(state.value(QStringLiteral("navigation")).toMap()))) return false;
    if (state == m_state) return true;
    if (m_revision == std::numeric_limits<qulonglong>::max()) return false;
    m_state = state;
    ++m_revision;
    for (auto session = m_sessions.cbegin(); session != m_sessions.cend(); ++session) {
        sendSignal(session.key(), session.value(), sessionInterface, QStringLiteral("StateChanged"),
                   QVariantList() << QVariant::fromValue(m_revision) << m_state);
        if (m_navigation)
            sendSignal(session.key(), session.value(), navigationInterface, QStringLiteral("GuidanceChanged"),
                QVariantList() << QVariant::fromValue(m_revision) << m_state.value(QStringLiteral("navigation")).toMap());
    }
    return true;
}

void SailplayProvider::setActionHandler(const QString &action,
                                      const std::function<void(qulonglong, const QVariantMap &)> &handler)
{
    if (QThread::currentThread() == thread() && validString(action) && handler) m_actions.insert(action, handler);
}

bool SailplayProvider::invoke(const QDBusMessage &message, const QDBusConnection &connection)
{
    const QVariantList arguments = message.arguments();
    const QString action = arguments.at(1).toString();
    if (!m_actions.contains(action))
        return errorReply(message, connection, errorPrefix + QStringLiteral("NotSupported"),
                          QStringLiteral("Application action is unavailable"));
    Session &session = m_sessions[message.path()];
    const qulonglong requestId = arguments.first().toULongLong();
    const qulonglong expected = arguments.at(3).toULongLong();
    const QVariantMap parameters = qdbus_cast<QVariantMap>(arguments.at(2));
    if (requestId == 0 || !validState(parameters))
        return errorReply(message, connection, errorPrefix + QStringLiteral("InvalidArgument"),
                          QStringLiteral("A positive request ID and valid parameters are required"));
    if (requestId <= session.lastRequest)
        return errorReply(message, connection, errorPrefix + QStringLiteral("DuplicateRequest"),
                          QStringLiteral("Request IDs must increase within a presentation session"));
    if (expected != 0 && expected != m_revision)
        return errorReply(message, connection, errorPrefix + QStringLiteral("StaleRevision"),
                          QStringLiteral("Application state has changed"));
    if (session.pending.size() >= 64 || m_pending.size() >= 4096
        || m_nextInvocation == std::numeric_limits<qulonglong>::max())
        return errorReply(message, connection, errorPrefix + QStringLiteral("LimitExceeded"),
                          QStringLiteral("Application request limit reached"));
    const qulonglong invocation = ++m_nextInvocation;
    session.lastRequest = requestId;
    session.pending.insert(invocation);
    m_pending.insert(invocation, {message.path(), message.service(), requestId, expected});
    const auto handler = m_actions.value(action);
    connection.send(message.createReply());
    QTimer::singleShot(0, this, [this, invocation, parameters, handler] {
        if (!m_pending.contains(invocation)) return;
        try {
            handler(invocation, parameters);
        } catch (const std::exception &error) {
            fail(invocation, QStringLiteral("Failed"), QString::fromUtf8(error.what()));
        } catch (...) {
            fail(invocation, QStringLiteral("Failed"), QStringLiteral("Application action failed"));
        }
    });
    emit pendingChanged();
    return true;
}

bool SailplayProvider::complete(qulonglong invocation, const QVariantMap &result)
{
    if (!validState(result)) return false;
    return finish(invocation, result, QString(), QString());
}

bool SailplayProvider::complete(qulonglong invocation, const QVariantMap &result, const QVariantMap &state)
{
    if (QThread::currentThread() != thread() || !m_pending.contains(invocation) || !validState(result)) return false;
    const qulonglong expected = m_pending.value(invocation).expectedRevision;
    if (expected != 0 && expected != m_revision)
        return fail(invocation, QStringLiteral("StaleRevision"), QStringLiteral("Application state has changed"));
    if (!publish(state)) return false;
    return complete(invocation, result);
}

bool SailplayProvider::fail(qulonglong invocation, const QString &code, const QString &message)
{
    if (!validString(code) || message.contains(QChar::Null)) return false;
    return finish(invocation, QVariantMap(), errorPrefix + code, message);
}

bool SailplayProvider::finish(qulonglong invocation, const QVariantMap &result,
                              const QString &error, const QString &message)
{
    if (QThread::currentThread() != thread() || !m_pending.contains(invocation)) return false;
    const Invocation accepted = m_pending.take(invocation);
    auto session = m_sessions.find(accepted.path);
    if (session != m_sessions.end() && session->owner == accepted.owner) {
        session->pending.remove(invocation);
        sendSignal(accepted.path, session.value(), sessionInterface, QStringLiteral("RequestFinished"),
            QVariantList() << QVariant::fromValue(accepted.requestId) << QVariant::fromValue(m_revision)
                << result << error << message);
    }
    emit pendingChanged();
    return true;
}

QVariantMap SailplayProvider::navigationGuidance(const QString &state)
{
    return {{QStringLiteral("state"), state}, {QStringLiteral("mode"), QStringLiteral("driving")},
        {QStringLiteral("maneuver"), QStringLiteral("unknown")}, {QStringLiteral("drivingSide"), QStringLiteral("right")},
        {QStringLiteral("exitNumber"), uint(0)}, {QStringLiteral("nextDistanceMeters"), 0.0},
        {QStringLiteral("remainingDistanceMeters"), 0.0}, {QStringLiteral("remainingSeconds"), qulonglong(0)},
        {QStringLiteral("currentRoad"), QString()}, {QStringLiteral("nextRoad"), QString()},
        {QStringLiteral("destination"), QString()}, {QStringLiteral("updatedMs"), boottimeMs()}};
}

bool SailplayProvider::validGuidance(const QVariantMap &value)
{
    const QVariantMap defaults = navigationGuidance();
    if (value.keys() != defaults.keys()) return false;
    for (auto field = defaults.cbegin(); field != defaults.cend(); ++field) {
        if (value.value(field.key()).type() != field.value().type()) return false;
    }
    const QMap<QString, QStringList> enums = {
        {QStringLiteral("state"), {QStringLiteral("idle"), QStringLiteral("active"), QStringLiteral("unavailable"),
                                  QStringLiteral("stopped"), QStringLiteral("arrived")}},
        {QStringLiteral("mode"), {QStringLiteral("driving"), QStringLiteral("walking"), QStringLiteral("cycling"), QStringLiteral("transit")}},
        {QStringLiteral("drivingSide"), {QStringLiteral("left"), QStringLiteral("right")}},
        {QStringLiteral("maneuver"), {QStringLiteral("unknown"), QStringLiteral("continue"), QStringLiteral("slight-left"),
            QStringLiteral("slight-right"), QStringLiteral("turn-left"), QStringLiteral("turn-right"), QStringLiteral("sharp-left"),
            QStringLiteral("sharp-right"), QStringLiteral("uturn"), QStringLiteral("roundabout-enter"), QStringLiteral("roundabout-exit"),
            QStringLiteral("roundabout-continue"), QStringLiteral("exit-left"), QStringLiteral("exit-right"), QStringLiteral("arrive")}}
    };
    for (auto field = enums.cbegin(); field != enums.cend(); ++field) {
        if (!field.value().contains(value.value(field.key()).toString())) return false;
    }
    for (const QString &key : {QStringLiteral("nextDistanceMeters"), QStringLiteral("remainingDistanceMeters")}) {
        const double distance = value.value(key).toDouble();
        if (!std::isfinite(distance) || distance < 0) return false;
    }
    for (const QString &key : {QStringLiteral("currentRoad"), QStringLiteral("nextRoad"), QStringLiteral("destination")}) {
        const QString text = value.value(key).toString();
        if (text.toUcs4().size() > 1024 || text.contains(QChar::Null)) return false;
    }
    return value.value(QStringLiteral("updatedMs")).toULongLong() <= boottimeMs();
}
