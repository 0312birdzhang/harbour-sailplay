#include "contenthost.h"
#include "sailplaycontent.h"

#include <QCoreApplication>
#include <QSet>
#include <QSignalBlocker>
#include <QVector>

namespace {
QString translated(const char *message)
{
    return QCoreApplication::translate("Sailplay", message);
}
}

SailplayContentHost::SailplayContentHost(QObject *parent) : QObject(parent), m_session(this)
{
    connect(&m_session, &SailplaySession::stateChanged, this, &SailplayContentHost::receiveState);
    connect(&m_session, &SailplaySession::readyChanged, this, [this](bool ready) {
        if (ready && m_session.applicationId() != m_declaration.applicationId) {
            m_session.close();
            fail(translated("Content provider identity does not match its desktop declaration"));
            return;
        }
        if (ready) {
            m_session.setActive(m_active);
            if (m_location.id != QStringLiteral("root") || !m_location.query.isEmpty()) requestPage();
        }
        emit changed();
    });
    connect(&m_session, &SailplaySession::errorOccurred, this,
        [this](const QString &, const QString &message) { m_request = 0; m_activatedItem.clear(); fail(message); });
    connect(&m_session, &SailplaySession::requestFinished, this,
        [this](qulonglong id, qulonglong, const QVariantMap &result, const QString &error, const QString &message) {
            if (id != m_request) return;
            m_request = 0;
            const QString activated = m_activatedItem;
            m_activatedItem.clear();
            if (!error.isEmpty()) { fail(message); return; }
            if (!m_pageRequest) {
                refresh();
                if (!activated.isEmpty()) emit itemActivated(activated);
                return;
            }
            const QVariantMap page = SailplayContent::decode(result.value(QStringLiteral("content"))).toMap();
            if (!SailplayContent::validPage(page) || page.value("id").toString() != m_location.id
                || page.value("offset").toUInt() != m_offset) {
                fail(translated("Content provider returned an invalid page"));
                return;
            }
            if (page.value("version").toULongLong() != m_requestedVersion
                || m_root.value("version").toULongLong() != m_requestedVersion) {
                requestPage();
                return;
            }
            const QVariantMap presentation =
                SailplayContent::cleanPresentation(result.value(QStringLiteral("presentation")), page);
            const QVariantList incoming =
                SailplayContent::presentedItems(page.value("items").toList(), presentation);
            if (!m_offset && enterTabs(page, incoming, presentation)) return;
            QVariantList items = m_offset ? m_items : QVariantList();
            QSet<QString> ids;
            for (const QVariant &entry : items) ids.insert(entry.toMap().value("id").toString());
            for (const QVariant &entry : incoming) {
                const QString identity = entry.toMap().value("id").toString();
                if (ids.contains(identity)) { fail(translated("Content provider returned an invalid page")); return; }
                ids.insert(identity);
                items.append(entry);
            }
            present(page, items, presentation);
        });
}

SailplayContentHost::~SailplayContentHost()
{
    close();
}

void SailplayContentHost::open(const SailplayApplication &declaration, const QString &name)
{
    if (declaration.presentationId() == m_declaration.presentationId() && m_error.isEmpty()) return;
    close();
    m_declaration = declaration;
    m_name = name;
    if (!declaration.contentTemplate()) { fail(translated("Unsupported content provider")); return; }
    m_session.open(declaration.service, declaration.path, QStringLiteral("car"), {QStringLiteral("content")});
    emit changed();
}

void SailplayContentHost::setActive(bool active)
{
    m_active = active;
    if (ready()) m_session.setActive(active);
}

void SailplayContentHost::close()
{
    const QSignalBlocker blocker(&m_session);
    m_session.close();
    m_request = 0;
    m_activatedItem.clear();
    m_page.clear();
    m_root.clear();
    m_rootPresentation.clear();
    m_layout = QStringLiteral("list");
    m_items.clear();
    m_history.clear();
    m_location = Location();
    m_declaration = SailplayApplication();
    m_name.clear();
    m_error.clear();
    emit changed();
}

void SailplayContentHost::receiveState()
{
    if (!m_session.revision()) {
        m_request = 0;
        m_root.clear();
        m_rootPresentation.clear();
        m_page.clear();
        m_items.clear();
    } else {
        const QVariantMap root = SailplayContent::decode(m_session.state().value(QStringLiteral("content"))).toMap();
        if (!SailplayContent::validRoot(root)) {
            m_session.close();
            fail(translated("Content provider returned an invalid page"));
            return;
        }
        const QVariantMap presentation = SailplayContent::cleanPresentation(
            m_session.state().value(QStringLiteral("contentPresentation")), root);
        const bool contentChanged = root != m_root || presentation != m_rootPresentation;
        m_root = root;
        m_rootPresentation = presentation;
        // A pending action remains pending across its own state publication.
        if (contentChanged && !busy()) refresh();
    }
    emit changed();
}

void SailplayContentHost::requestPage(uint offset)
{
    if (!ready()) return;
    m_offset = offset;
    m_requestedVersion = m_root.value("version").toULongLong();
    m_pageRequest = true;
    QVariantMap parameters = {{"id", m_location.id}, {"offset", offset}, {"limit", uint(50)}};
    const bool search = !m_location.query.isEmpty();
    if (search) parameters.insert(QStringLiteral("query"), m_location.query);
    m_request = m_session.invoke(search ? QStringLiteral("content.search") : QStringLiteral("content.browse"),
                                parameters);
    m_error.clear();
    emit changed();
}

void SailplayContentHost::present(const QVariantMap &page, const QVariantList &items, const QVariantMap &presentation)
{
    m_page = page;
    m_items = items;
    m_layout = presentation.value(QStringLiteral("layout"), QStringLiteral("list")).toString();
    m_error.clear();
    emit changed();
}

// A tabbed page lists folders only. Its folders become a tab bar and the host
// shows the selected folder beneath it, without adding to the browsing history.
bool SailplayContentHost::enterTabs(const QVariantMap &page, const QVariantList &items, const QVariantMap &presentation)
{
    if (!presentation.value(QStringLiteral("tabs")).toBool() || !m_location.tabs.isEmpty()
        || !m_location.query.isEmpty() || page.value("hasMore").toBool() || items.isEmpty() || items.size() > 12)
        return false;
    QString first;
    for (const QVariant &entry : items) {
        const QVariantMap item = entry.toMap();
        if (item.value("kind") != QStringLiteral("folder")) return false;
        if (first.isEmpty() && item.value("enabled").toBool()) first = item.value("id").toString();
    }
    if (first.isEmpty()) return false;
    m_location.tabs = items;
    m_location.tabsOwner = page.value("id").toString();
    m_location.id = first;
    m_page.clear();
    m_items.clear();
    requestPage();
    return true;
}

void SailplayContentHost::refresh()
{
    m_request = 0;
    if (m_location.tabsOwner == QStringLiteral("root") && m_location.query.isEmpty() && !m_root.isEmpty()) {
        // The root's folders may have changed: rebuild its tab bar, keeping the selected tab when it remains.
        const QString selected = m_location.id;
        m_location = Location();
        const QVariantList items = SailplayContent::presentedItems(m_root.value("items").toList(), m_rootPresentation);
        if (enterTabs(m_root, items, m_rootPresentation)) {
            for (const QVariant &entry : m_location.tabs) {
                const QVariantMap item = entry.toMap();
                if (item.value("id").toString() == selected && item.value("enabled").toBool()
                    && m_location.id != selected) {
                    m_location.id = selected;
                    requestPage();
                }
            }
            return;
        }
    }
    if (m_location.id == QStringLiteral("root") && m_location.query.isEmpty() && !m_root.isEmpty()) {
        const QVariantList items = SailplayContent::presentedItems(m_root.value("items").toList(), m_rootPresentation);
        if (enterTabs(m_root, items, m_rootPresentation)) return;
        present(m_root, items, m_rootPresentation);
    } else requestPage();
}

void SailplayContentHost::selectTab(const QString &id)
{
    if (!ready() || busy() || id == m_location.id) return;
    for (const QVariant &entry : m_location.tabs) {
        const QVariantMap item = entry.toMap();
        if (item.value("id").toString() != id || !item.value("enabled").toBool()) continue;
        m_location.id = id;
        m_location.query.clear();
        m_page.clear();
        m_items.clear();
        requestPage();
        return;
    }
}

void SailplayContentHost::invokeItem(const QVariantMap &item, bool listItem)
{
    if (!ready() || busy() || !item.value("enabled").toBool()) return;
    if (item.value("kind") == QStringLiteral("folder")) {
        if (m_history.size() >= 32) { fail(translated("Content history limit reached")); return; }
        m_history.append(m_location);
        m_location = Location();
        m_location.id = item.value("id").toString();
        m_page.clear();
        m_items.clear();
        requestPage();
    } else {
        m_pageRequest = false;
        m_activatedItem = listItem ? item.value("id").toString() : QString();
        m_request = m_session.invoke(item.value("action").toString(), item.value("parameters").toMap(), m_session.revision());
        emit changed();
    }
}

void SailplayContentHost::select(const QString &id)
{
    for (const QVariant &item : m_items) {
        if (item.toMap().value("id").toString() == id) { invokeItem(item.toMap(), true); return; }
    }
}

void SailplayContentHost::action(const QString &id)
{
    for (const QVariant &item : m_page.value("actions").toList()) {
        if (item.toMap().value("id").toString() == id) { invokeItem(item.toMap()); return; }
    }
}

void SailplayContentHost::search(const QString &query)
{
    if (!ready() || !m_page.value("searchEnabled").toBool() || query.toUcs4().size() > 256
        || query.contains(QChar::Null)) return;
    if (!query.isEmpty() && m_location.query.isEmpty()) {
        if (m_history.size() >= 32) { fail(translated("Content history limit reached")); return; }
        m_history.append(m_location);
    }
    m_location.query = query;
    m_items.clear();
    requestPage();
}

void SailplayContentHost::back()
{
    if (m_history.isEmpty()) return;
    m_location = m_history.takeLast();
    refresh();
}

void SailplayContentHost::more()
{
    if (!ready() || busy() || !m_page.value("hasMore").toBool()) return;
    if (m_items.size() >= 500) m_items.clear();
    requestPage(m_page.value("offset").toUInt() + m_page.value("items").toList().size());
}

void SailplayContentHost::fail(const QString &message)
{
    m_error = message;
    emit changed();
}
