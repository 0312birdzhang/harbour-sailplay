#ifndef SAILPLAY_CONTENT_HOST_H
#define SAILPLAY_CONTENT_HOST_H

#include "sailplayapplication.h"
#include "sailplaysession.h"

class SailplayContentHost : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool ready READ ready NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool canGoBack READ canGoBack NOTIFY changed)
    Q_PROPERTY(QString applicationId READ applicationId NOTIFY changed)
    Q_PROPERTY(QString name READ name NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(QVariantMap page READ page NOTIFY changed)
    Q_PROPERTY(QVariantList items READ items NOTIFY changed)

public:
    explicit SailplayContentHost(QObject *parent = nullptr);
    ~SailplayContentHost() override;
    bool ready() const { return m_session.ready(); }
    bool busy() const { return m_request != 0; }
    bool canGoBack() const { return !m_history.isEmpty(); }
    QString applicationId() const { return m_declaration.presentationId(); }
    QString name() const { return m_name; }
    QString error() const { return m_error; }
    QVariantMap page() const { return m_page; }
    QVariantList items() const { return m_items; }
    void open(const SailplayApplication &declaration, const QString &name);
    void setActive(bool active);
    void close();
    Q_INVOKABLE void select(const QString &id);
    Q_INVOKABLE void action(const QString &id);
    Q_INVOKABLE void search(const QString &query);
    Q_INVOKABLE void back();
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void more();

signals:
    void changed();

private:
    struct Location {
        QString id = QStringLiteral("root");
        QString query;
    };
    void receiveState();
    void requestPage(uint offset = 0);
    void invokeItem(const QVariantMap &item);
    void fail(const QString &message);
    SailplaySession m_session;
    SailplayApplication m_declaration;
    QString m_name;
    QString m_error;
    QVariantMap m_root;
    QVariantMap m_page;
    QVariantList m_items;
    QList<Location> m_history;
    Location m_location;
    qulonglong m_request = 0;
    qulonglong m_requestedVersion = 0;
    uint m_offset = 0;
    bool m_pageRequest = false;
    bool m_active = true;
};

#endif
