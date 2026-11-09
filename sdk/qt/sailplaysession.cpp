#include "sailplaysession.h"
#include "app1_interface.h"
#include "session1_interface.h"

#include <QDBusArgument>
#include <QDBusMessage>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusServiceWatcher>
#include <limits>

namespace {
const QString appInterface = QStringLiteral("org.sailplay.App1");
const QString sessionInterface = QStringLiteral("org.sailplay.Session1");
const QString errorPrefix = QStringLiteral("org.sailplay.Error1.");

QDBusMessage daemonCall(const QString &member, const QVariantList &arguments)
{
    QDBusMessage message = QDBusMessage::createMethodCall(QStringLiteral("org.freedesktop.DBus"),
        QStringLiteral("/org/freedesktop/DBus"), QStringLiteral("org.freedesktop.DBus"), member);
    message.setArguments(arguments);
    return message;
}
}

SailplaySession::SailplaySession(QObject *parent)
    : SailplaySession(QDBusConnection::sessionBus(), parent)
{
}

SailplaySession::SailplaySession(const QDBusConnection &bus, QObject *parent)
    : QObject(parent), m_bus(bus),
      m_watcher(new QDBusServiceWatcher(QString(), bus, QDBusServiceWatcher::WatchForOwnerChange, this))
{
    connect(m_watcher, &QDBusServiceWatcher::serviceOwnerChanged, this,
        [this](const QString &service, const QString &, const QString &owner) {
            if (service != m_service || owner == m_owner) return;
            const qulonglong generation = ++m_generation;
            reset();
            if (!owner.isEmpty()) connectOwner(generation, owner);
        });
}

SailplaySession::~SailplaySession()
{
    close();
}

void SailplaySession::open(const QString &service, const QString &path,
                          const QString &presentation, const QStringList &requiredCapabilities)
{
    close();
    if (service.isEmpty() || service.startsWith(QLatin1Char(':')) || !path.startsWith(QLatin1Char('/'))
        || (presentation != QStringLiteral("phone") && presentation != QStringLiteral("car"))) {
        emit errorOccurred(errorPrefix + QStringLiteral("InvalidArgument"),
                           QStringLiteral("An application service and phone/car presentation are required"));
        return;
    }
    m_service = service;
    m_path = path;
    m_presentation = presentation;
    m_required = requiredCapabilities;
    m_watcher->setWatchedServices(QStringList() << service);
    discover(m_generation, true);
}

void SailplaySession::discover(qulonglong generation, bool activate)
{
    auto *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(
        daemonCall(QStringLiteral("GetNameOwner"), QVariantList() << m_service), 5000), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
        [this, generation, activate](QDBusPendingCallWatcher *watcher) {
            QDBusPendingReply<QString> reply = *watcher;
            watcher->deleteLater();
            if (generation != m_generation) return;
            if (!reply.isError()) {
                connectOwner(generation, reply.value());
                return;
            }
            if (!activate || reply.error().name() != QStringLiteral("org.freedesktop.DBus.Error.NameHasNoOwner")) {
                fail(generation, reply.error().name(), reply.error().message());
                return;
            }
            auto *activation = new QDBusPendingCallWatcher(m_bus.asyncCall(
                daemonCall(QStringLiteral("StartServiceByName"), QVariantList() << m_service << uint(0)), 5000), this);
            connect(activation, &QDBusPendingCallWatcher::finished, this,
                [this, generation](QDBusPendingCallWatcher *watcher) {
                    QDBusPendingReply<uint> started = *watcher;
                    watcher->deleteLater();
                    if (generation != m_generation) return;
                    if (started.isError()) fail(generation, started.error().name(), started.error().message());
                    else discover(generation, false);
                });
        });
}

void SailplaySession::connectOwner(qulonglong generation, const QString &owner)
{
    if (generation != m_generation) return;
    m_owner = owner;
    QDBusMessage message = QDBusMessage::createMethodCall(owner, m_path,
        QStringLiteral("org.freedesktop.DBus.Properties"), QStringLiteral("GetAll"));
    message << appInterface;
    auto *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message, 5000), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
        [this, generation, owner](QDBusPendingCallWatcher *watcher) {
            QDBusPendingReply<QVariantMap> reply = *watcher;
            watcher->deleteLater();
            if (generation != m_generation) return;
            if (reply.isError()) {
                fail(generation, reply.error().name(), reply.error().message());
                return;
            }
            const QVariantMap info = reply.value();
            m_applicationId = info.value(QStringLiteral("ApplicationId")).toString();
            m_instanceId = info.value(QStringLiteral("InstanceId")).toString();
            m_capabilities = qdbus_cast<QStringList>(info.value(QStringLiteral("Capabilities")));
            if (info.value(QStringLiteral("ApiVersion")).toUInt() != 1
                || m_applicationId.isEmpty() || m_instanceId.isEmpty()) {
                fail(generation, errorPrefix + QStringLiteral("NotSupported"),
                     QStringLiteral("Application SDK version or identity is unavailable"));
                return;
            }
            for (const QString &capability : m_required) {
                if (!m_capabilities.contains(capability)) {
                    fail(generation, errorPrefix + QStringLiteral("NotSupported"),
                         QStringLiteral("A required capability is unavailable"));
                    return;
                }
            }
            emit applicationChanged();
            openSession(generation, owner);
        });
}

void SailplaySession::openSession(qulonglong generation, const QString &owner)
{
    if (generation != m_generation) return;
    m_app = new OrgSailplayApp1Interface(owner, m_path, m_bus, this);
    auto *watcher = new QDBusPendingCallWatcher(m_app->OpenSession(m_presentation, m_required), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
        [this, generation, owner](QDBusPendingCallWatcher *watcher) {
            QDBusPendingReply<QDBusObjectPath> reply = *watcher;
            watcher->deleteLater();
            if (generation != m_generation) {
                if (!reply.isError()) retire(owner, reply.value().path());
                return;
            }
            if (reply.isError()) {
                fail(generation, reply.error().name(), reply.error().message());
                return;
            }
            m_sessionPath = reply.value().path();
            m_session = new OrgSailplaySession1Interface(owner, m_sessionPath, m_bus, this);
            connect(m_session, &OrgSailplaySession1Interface::StateChanged, this,
                [this, generation](qulonglong revision, const QVariantMap &state) {
                    receiveState(generation, revision, state);
                });
            connect(m_session, &OrgSailplaySession1Interface::RequestFinished, this,
                [this, generation](qulonglong request, qulonglong revision, const QVariantMap &result,
                                   const QString &name, const QString &message) {
                    if (generation == m_generation && m_pending.remove(request))
                        emit requestFinished(request, revision, result, name, message);
                });
            auto *snapshot = new QDBusPendingCallWatcher(m_session->GetSnapshot(), this);
            connect(snapshot, &QDBusPendingCallWatcher::finished, this,
                [this, generation](QDBusPendingCallWatcher *watcher) {
                    QDBusPendingReply<qulonglong, QVariantMap> reply = *watcher;
                    watcher->deleteLater();
                    if (generation != m_generation) return;
                    if (reply.isError()) {
                        fail(generation, reply.error().name(), reply.error().message());
                        return;
                    }
                    receiveState(generation, reply.argumentAt<0>(), reply.argumentAt<1>());
                    if (generation == m_generation) {
                        m_ready = true;
                        emit readyChanged(true);
                    }
                });
        });
}

void SailplaySession::receiveState(qulonglong generation, qulonglong revision, const QVariantMap &state)
{
    if (generation == m_generation && revision > m_revision) {
        m_revision = revision;
        m_state = state;
        emit stateChanged();
    }
}

qulonglong SailplaySession::invoke(const QString &action, const QVariantMap &parameters, qulonglong expectedRevision)
{
    if (!m_ready || !m_session) {
        emit errorOccurred(errorPrefix + QStringLiteral("Disconnected"), QStringLiteral("Presentation session is not ready"));
        return 0;
    }
    if (m_sequence == std::numeric_limits<qulonglong>::max()) {
        emit errorOccurred(errorPrefix + QStringLiteral("LimitExceeded"), QStringLiteral("Presentation request ID limit reached"));
        return 0;
    }
    const qulonglong request = ++m_sequence;
    const qulonglong generation = m_generation;
    m_pending.insert(request);
    auto *watcher = new QDBusPendingCallWatcher(m_session->Invoke(request, action, parameters, expectedRevision), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
        [this, generation, request](QDBusPendingCallWatcher *watcher) {
            QDBusPendingReply<> reply = *watcher;
            watcher->deleteLater();
            if (generation == m_generation && reply.isError() && m_pending.remove(request))
                emit requestFinished(request, m_revision, QVariantMap(), reply.error().name(), reply.error().message());
        });
    return request;
}

void SailplaySession::setActive(bool active)
{
    if (!m_ready || !m_session) {
        emit errorOccurred(errorPrefix + QStringLiteral("Disconnected"), QStringLiteral("Presentation session is not ready"));
        return;
    }
    const qulonglong generation = m_generation;
    auto *watcher = new QDBusPendingCallWatcher(m_session->SetActive(active), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
        [this, generation](QDBusPendingCallWatcher *watcher) {
            QDBusPendingReply<> reply = *watcher;
            watcher->deleteLater();
            if (reply.isError()) fail(generation, reply.error().name(), reply.error().message());
        });
}

void SailplaySession::fail(qulonglong generation, const QString &name, const QString &message)
{
    if (generation != m_generation) return;
    ++m_generation;
    reset();
    emit errorOccurred(name, message);
}

void SailplaySession::retire(const QString &owner, const QString &path)
{
    QDBusMessage message = QDBusMessage::createMethodCall(owner, path, sessionInterface, QStringLiteral("Close"));
    m_bus.asyncCall(message, 5000);
}

void SailplaySession::reset()
{
    if (!m_owner.isEmpty() && !m_sessionPath.isEmpty()) retire(m_owner, m_sessionPath);
    if (m_session) m_session->deleteLater();
    if (m_app) m_app->deleteLater();
    m_session = nullptr;
    m_app = nullptr;
    m_owner.clear();
    m_sessionPath.clear();
    m_sequence = 0;
    const QSet<qulonglong> pending = m_pending;
    m_pending.clear();
    const bool wasReady = m_ready;
    const bool hadState = m_revision > 0;
    m_ready = false;
    m_revision = 0;
    m_state.clear();
    m_applicationId.clear();
    m_instanceId.clear();
    m_capabilities.clear();
    emit applicationChanged();
    if (wasReady) emit readyChanged(false);
    if (hadState) emit stateChanged();
    for (qulonglong request : pending)
        emit requestFinished(request, 0, QVariantMap(), errorPrefix + QStringLiteral("Disconnected"),
                             QStringLiteral("Application session ended"));
}

void SailplaySession::close()
{
    m_service.clear();
    m_watcher->setWatchedServices(QStringList());
    ++m_generation;
    reset();
}
