#ifndef SAILPLAY_SESSION_H
#define SAILPLAY_SESSION_H

#include <QDBusConnection>
#include <QObject>
#include <QSet>
#include <QStringList>
#include <QVariantMap>

class QDBusServiceWatcher;
class OrgSailplayApp1Interface;
class OrgSailplaySession1Interface;

class SailplaySession : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool ready READ ready NOTIFY readyChanged)
    Q_PROPERTY(qulonglong revision READ revision NOTIFY stateChanged)
    Q_PROPERTY(QVariantMap state READ state NOTIFY stateChanged)
    Q_PROPERTY(QString applicationId READ applicationId NOTIFY applicationChanged)
    Q_PROPERTY(QString instanceId READ instanceId NOTIFY applicationChanged)
    Q_PROPERTY(QStringList capabilities READ capabilities NOTIFY applicationChanged)

public:
    explicit SailplaySession(QObject *parent = nullptr);
    SailplaySession(const QDBusConnection &bus, QObject *parent = nullptr);
    ~SailplaySession() override;

    bool ready() const { return m_ready; }
    qulonglong revision() const { return m_revision; }
    QVariantMap state() const { return m_state; }
    QString applicationId() const { return m_applicationId; }
    QString instanceId() const { return m_instanceId; }
    QStringList capabilities() const { return m_capabilities; }

    Q_INVOKABLE void open(const QString &service,
        const QString &path = QStringLiteral("/org/sailplay/v1/App"),
        const QString &presentation = QStringLiteral("car"),
        const QStringList &requiredCapabilities = QStringList());
    Q_INVOKABLE qulonglong invoke(const QString &action,
        const QVariantMap &parameters = QVariantMap(), qulonglong expectedRevision = 0);
    Q_INVOKABLE void setActive(bool active);
    Q_INVOKABLE void close();

signals:
    void readyChanged(bool ready);
    void stateChanged();
    void applicationChanged();
    void requestFinished(qulonglong requestId, qulonglong revision,
                         const QVariantMap &result, const QString &errorName,
                         const QString &errorMessage);
    void errorOccurred(const QString &name, const QString &message);

private:
    void discover(qulonglong generation, bool activate);
    void connectOwner(qulonglong generation, const QString &owner);
    void openSession(qulonglong generation, const QString &owner);
    void receiveState(qulonglong generation, qulonglong revision, const QVariantMap &state);
    void fail(qulonglong generation, const QString &name, const QString &message);
    void retire(const QString &owner, const QString &path);
    void reset();

    QDBusConnection m_bus;
    QDBusServiceWatcher *m_watcher;
    OrgSailplayApp1Interface *m_app = nullptr;
    OrgSailplaySession1Interface *m_session = nullptr;
    QString m_service;
    QString m_path;
    QString m_presentation;
    QStringList m_required;
    QString m_clientName;
    QString m_owner;
    QString m_sessionPath;
    QString m_applicationId;
    QString m_instanceId;
    QStringList m_capabilities;
    QVariantMap m_state;
    QSet<qulonglong> m_pending;
    qulonglong m_generation = 0;
    qulonglong m_sequence = 0;
    qulonglong m_revision = 0;
    bool m_ready = false;
};

#endif
