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
    Q_PROPERTY(QString layout READ layout NOTIFY changed)
    Q_PROPERTY(QVariantList tabs READ tabs NOTIFY changed)
    Q_PROPERTY(QString currentTab READ currentTab NOTIFY changed)
    Q_PROPERTY(QString currentItem READ currentItem NOTIFY changed)
    Q_PROPERTY(QVariantMap detail READ detail NOTIFY changed)
    Q_PROPERTY(QVariantMap side READ side NOTIFY changed)

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
    QString layout() const { return m_layout; }
    QVariantList tabs() const { return m_location.tabs; }
    QString currentTab() const { return m_location.tabs.isEmpty() ? QString() : m_location.id; }
    // In a split page: the chosen folder and its rows.
    QString currentItem() const { return m_location.master; }
    QVariantMap detail() const { return m_detail; }
    // The folder pinned by the root page, shown whatever is being browsed.
    QVariantMap side() const;
    void open(const SailplayApplication &declaration, const QString &name);
    void setActive(bool active);
    void close();
    Q_INVOKABLE void select(const QString &id);
    Q_INVOKABLE void selectTab(const QString &id);
    Q_INVOKABLE void selectDetail(const QString &id);
    Q_INVOKABLE void moreDetail();
    Q_INVOKABLE void selectSide(const QString &id);
    Q_INVOKABLE void sideAction(const QString &id);
    Q_INVOKABLE void moreSide();
    Q_INVOKABLE void action(const QString &id);
    Q_INVOKABLE void search(const QString &query);
    Q_INVOKABLE void back();
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void more();

signals:
    void changed();
    // A list item's own action (not a folder or a page control) succeeded.
    void itemActivated(const QString &id);

private:
    struct Location {
        QString id = QStringLiteral("root");
        QString query;
        // Folders of a tabbed page, shown above the selected one's content.
        QVariantList tabs;
        QString tabsOwner;
        // Chosen folder of a split page.
        QString master;
    };
    enum Target { Main, Detail, Side };
    void receiveState();
    void present(const QVariantMap &page, const QVariantList &items, const QVariantMap &presentation);
    bool enterTabs(const QVariantMap &page, const QVariantList &items, const QVariantMap &presentation);
    QVariantList withoutSide(const QVariantMap &page, const QVariantList &items) const;
    void chooseMaster();
    void pump();
    void requestPane(Target target, uint offset);
    void receivePane(const QVariantMap &result);
    void requestPage(uint offset = 0);
    void invokeItem(const QVariantMap &item, bool listItem = false);
    void fail(const QString &message);
    SailplaySession m_session;
    SailplayApplication m_declaration;
    QString m_name;
    QString m_error;
    QVariantMap m_root;
    QVariantMap m_rootPresentation;
    QString m_layout = QStringLiteral("list");
    QVariantMap m_detail;
    QVariantMap m_side;
    QString m_sideId;
    Target m_target = Main;
    uint m_paneOffset = 0;
    bool m_detailWanted = false;
    bool m_sideWanted = false;
    QVariantMap m_page;
    QVariantList m_items;
    QList<Location> m_history;
    Location m_location;
    qulonglong m_request = 0;
    qulonglong m_requestedVersion = 0;
    uint m_offset = 0;
    bool m_pageRequest = false;
    QString m_activatedItem;
    bool m_active = true;
};

#endif
