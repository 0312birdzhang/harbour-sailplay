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
#include <QUuid>
#include <QXmlStreamReader>
#include <limits>

static void initializeSailplayContracts()
{
    Q_INIT_RESOURCE(qmake_sailplay_contracts);
}

namespace {
const QString appInterface = QStringLiteral("org.sailplay.App1");
const QString sessionInterface = QStringLiteral("org.sailplay.Session1");
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
    m_valid = validString(applicationId) && validState(state)
        && !m_appContract.xml.isEmpty() && !m_sessionContract.xml.isEmpty();
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
    if (!m_valid || !m_bus.isConnected() || !path.startsWith(QLatin1Char('/'))
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
    if (hadSessions) emit sessionsChanged();
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
    if (m_sessions.contains(path)) return m_sessionContract.xml;
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
        return errorReply(message, connection, errorPrefix + QStringLiteral("NotSupported"),
                          QStringLiteral("Application action is unavailable"));
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
    if (QThread::currentThread() != thread() || !validState(state) || !m_valid) return false;
    if (state == m_state) return true;
    if (m_revision == std::numeric_limits<qulonglong>::max()) return false;
    m_state = state;
    ++m_revision;
    for (auto session = m_sessions.cbegin(); session != m_sessions.cend(); ++session)
        sendSignal(session.key(), session.value(), sessionInterface, QStringLiteral("StateChanged"),
                   QVariantList() << QVariant::fromValue(m_revision) << m_state);
    return true;
}
