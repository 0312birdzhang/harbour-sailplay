#ifndef SAILPLAY_PROVIDER_H
#define SAILPLAY_PROVIDER_H

#include <QDBusConnection>
#include <QDBusVirtualObject>
#include <QHash>
#include <QStringList>
#include <QVariantMap>

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
    QString introspect(const QString &path) const override;
    bool handleMessage(const QDBusMessage &message, const QDBusConnection &connection) override;

signals:
    void sessionsChanged();

private:
    struct Session {
        QString owner;
        QString presentation;
        bool active = true;
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

    QDBusConnection m_bus;
    QDBusServiceWatcher *m_watcher;
    QString m_applicationId;
    QString m_instanceId;
    QStringList m_capabilities;
    QString m_path;
    QVariantMap m_state;
    QHash<QString, Session> m_sessions;
    Contract m_appContract;
    Contract m_sessionContract;
    qulonglong m_revision = 1;
    bool m_valid = false;
};

#endif
