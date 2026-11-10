#ifndef SAILPLAY_NAVIGATION_HOST_H
#define SAILPLAY_NAVIGATION_HOST_H

#include "sailplayapplication.h"
#include "sailplaysession.h"

#include <QTimer>

class SailplayNavigationHost : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool ready READ ready NOTIFY changed)
    Q_PROPERTY(QString applicationId READ applicationId NOTIFY changed)
    Q_PROPERTY(QString name READ name NOTIFY changed)
    Q_PROPERTY(QVariantMap guidance READ guidance NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)

public:
    explicit SailplayNavigationHost(const QString &runtime = QString(), QObject *parent = nullptr);
    ~SailplayNavigationHost() override;

    bool ready() const { return m_session.ready(); }
    QString applicationId() const { return m_declaration.applicationId; }
    QString name() const { return m_name; }
    QVariantMap guidance() const { return m_guidance; }
    QString error() const { return m_error; }

    void open(const SailplayApplication &declaration, const QString &name);
    void setActive(bool active);
    void close();
    Q_INVOKABLE void stopNavigation();

signals:
    void changed();

private:
    void receiveState();
    void publish();
    void removeExport();
    void fail(const QString &message);

    SailplaySession m_session;
    SailplayApplication m_declaration;
    QTimer m_heartbeat;
    QString m_name;
    QString m_error;
    QString m_directory;
    QString m_filename;
    QString m_bootId;
    QString m_startTicks;
    QVariantMap m_guidance;
    QByteArray m_lastExport;
    bool m_active = true;
};

#endif
