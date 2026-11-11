#ifndef SAILPLAY_PROVIDER_H
#define SAILPLAY_PROVIDER_H

#include <QDBusConnection>
#include <QDBusVirtualObject>
#include <QHash>
#include <QSet>
#include <QStringList>
#include <QVariantMap>

#include <functional>

class QDBusServiceWatcher;

// Export state and caller-owned presentation leases on the application's bus
// connection. The application retains ownership of its existing service name.
class SailplayProvider : public QDBusVirtualObject
{
    Q_OBJECT

public:
    SailplayProvider(const QString &applicationId, const QVariantMap &state,
                     const QStringList &capabilities = QStringList(), QObject *parent = nullptr);
    SailplayProvider(const QDBusConnection &bus, const QString &applicationId,
                     const QVariantMap &state, const QStringList &capabilities = QStringList(),
                     QObject *parent = nullptr);
    ~SailplayProvider() override;

    bool start(const QString &path = QStringLiteral("/org/sailplay/v1/App"));
    void close();
    bool publish(const QVariantMap &state);
    qulonglong revision() const { return m_revision; }
    QString instanceId() const { return m_instanceId; }
    int sessionCount() const { return m_sessions.size(); }
    int activeSessionCount() const;
    int pendingCount() const { return m_pending.size(); }
    void setActionHandler(const QString &action,
                          const std::function<void(qulonglong, const QVariantMap &)> &handler);
    bool complete(qulonglong invocation, const QVariantMap &result = QVariantMap());
    bool complete(qulonglong invocation, const QVariantMap &result, const QVariantMap &state);
    bool fail(qulonglong invocation, const QString &code, const QString &message);
    static QVariantMap navigationGuidance(const QString &state = QStringLiteral("idle"));
    QString introspect(const QString &path) const override;
    bool handleMessage(const QDBusMessage &message, const QDBusConnection &connection) override;

signals:
    void sessionsChanged();
    void pendingChanged();

private:
    struct Session {
        QString owner;
        QString presentation;
        bool active = true;
        qulonglong lastRequest = 0;
        QSet<qulonglong> pending;
    };
    struct Invocation {
        QString path;
        QString owner;
        qulonglong requestId;
        qulonglong expectedRevision;
    };
    struct Contract {
        QString xml;
        QHash<QString, QString> methods;
    };
    bool properties(const QDBusMessage &message, const QDBusConnection &connection,
                    const QString &interface, const QVariantMap &values);
    void sendSignal(const QString &path, const Session &session, const QString &interface,
                    const QString &member, const QVariantList &arguments);
    void ownerLost(const QString &owner);
    static Contract readContract(const QString &interface);
    static bool validState(const QVariantMap &state);
    static bool validValue(const QVariant &value, int depth = 0);
    static bool validGuidance(const QVariantMap &guidance);
    bool finish(qulonglong invocation, const QVariantMap &result,
                const QString &error, const QString &message);
    bool invoke(const QDBusMessage &message, const QDBusConnection &connection);

    QDBusConnection m_bus;
    QDBusServiceWatcher *m_watcher;
    QString m_applicationId;
    QString m_instanceId;
    QStringList m_capabilities;
    QString m_path;
    QVariantMap m_state;
    QHash<QString, Session> m_sessions;
    QHash<qulonglong, Invocation> m_pending;
    QHash<QString, std::function<void(qulonglong, const QVariantMap &)>> m_actions;
    Contract m_appContract;
    Contract m_sessionContract;
    Contract m_navigationContract;
    Contract m_contentContract;
    qulonglong m_revision = 1;
    qulonglong m_nextInvocation = 0;
    bool m_navigation = false;
    bool m_content = false;
    bool m_valid = false;
};

#endif
