#ifndef SAILPLAY_NAVIGATION_HOST_H
#define SAILPLAY_NAVIGATION_HOST_H

#include "sailplayapplication.h"
#include "sailplaysession.h"

#include <QTimer>
#include <QImage>
#include <QQueue>

class SailplayNavigationHost : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool ready READ ready NOTIFY changed)
    Q_PROPERTY(QString applicationId READ applicationId NOTIFY changed)
    Q_PROPERTY(QString name READ name NOTIFY changed)
    Q_PROPERTY(QVariantMap guidance READ guidance NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(bool mapAvailable READ mapAvailable NOTIFY changed)
    Q_PROPERTY(bool mapReady READ mapReady NOTIFY mapChanged)
    Q_PROPERTY(QVariantMap mapState READ mapState NOTIFY mapChanged)

public:
    explicit SailplayNavigationHost(const QString &runtime = QString(), QObject *parent = nullptr);
    ~SailplayNavigationHost() override;

    bool ready() const { return m_session.ready(); }
    QString applicationId() const { return m_declaration.presentationId(); }
    QString name() const { return m_name; }
    QVariantMap guidance() const { return m_guidance; }
    QString error() const { return m_error; }
    bool mapAvailable() const { return ready() && m_session.capabilities().contains(QStringLiteral("navigation-map")); }
    bool mapReady() const { return !m_mapImage.isNull(); }
    QVariantMap mapState() const { return m_mapState; }
    QImage mapImage() const { return m_mapImage; }

    void open(const SailplayApplication &declaration, const QString &name);
    void setActive(bool active);
    void close();
    Q_INVOKABLE void stopNavigation();
    Q_INVOKABLE void configureMap(int width, int height);
    Q_INVOKABLE void mapTouch(const QString &phase, double x, double y);
    Q_INVOKABLE void mapControl(const QString &command);

signals:
    void changed();
    void mapChanged();

private:
    void receiveState();
    void publish();
    void removeExport();
    void fail(const QString &message);
    void requestMap();
    void sendTouch();
    void resetMap();
    void receiveMap(const QVariantMap &result);

    SailplaySession m_session;
    SailplayApplication m_declaration;
    QTimer m_heartbeat;
    QTimer m_mapTimer;
    QSize m_mapSize;
    QImage m_mapImage;
    QVariantMap m_mapState;
    QQueue<QVariantMap> m_touches;
    qulonglong m_mapRequest = 0;
    qulonglong m_touchRequest = 0;
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
