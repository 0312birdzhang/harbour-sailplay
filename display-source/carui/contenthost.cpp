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
        [this](const QString &, const QString &message) { m_request = 0; fail(message); });
    connect(&m_session, &SailplaySession::requestFinished, this,
        [this](qulonglong id, qulonglong, const QVariantMap &result, const QString &error, const QString &message) {
            if (id != m_request) return;
            m_request = 0;
            if (!error.isEmpty()) { fail(message); return; }
            if (!m_pageRequest) { refresh(); return; }
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
            const QVariantList incoming = page.value("items").toList();
            QVariantList items = m_offset ? m_items : QVariantList();
            QSet<QString> ids;
            for (const QVariant &entry : items) ids.insert(entry.toMap().value("id").toString());
            for (const QVariant &entry : incoming) {
                const QString identity = entry.toMap().value("id").toString();
                if (ids.contains(identity)) { fail(translated("Content provider returned an invalid page")); return; }
                ids.insert(identity);
                items.append(entry);
            }
            m_page = page;
            m_items = items;
            m_error.clear();
            emit changed();
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
    m_page.clear();
    m_root.clear();
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
        m_page.clear();
        m_items.clear();
    } else {
        const QVariantMap root = SailplayContent::decode(m_session.state().value(QStringLiteral("content"))).toMap();
        if (!SailplayContent::validRoot(root)) {
            m_session.close();
            fail(translated("Content provider returned an invalid page"));
            return;
        }
        const bool contentChanged = root != m_root;
        m_root = root;
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

void SailplayContentHost::refresh()
{
    m_request = 0;
    if (m_location.id == QStringLiteral("root") && m_location.query.isEmpty() && !m_root.isEmpty()) {
        m_page = m_root;
        m_items = m_root.value("items").toList();
        m_error.clear();
        emit changed();
    } else requestPage();
}

void SailplayContentHost::invokeItem(const QVariantMap &item)
{
    if (!ready() || busy() || !item.value("enabled").toBool()) return;
    if (item.value("kind") == QStringLiteral("folder")) {
        if (m_history.size() >= 32) { fail(translated("Content history limit reached")); return; }
        m_history.append(m_location);
        m_location.id = item.value("id").toString();
        m_location.query.clear();
        m_page.clear();
        m_items.clear();
        requestPage();
    } else {
        m_pageRequest = false;
        m_request = m_session.invoke(item.value("action").toString(), item.value("parameters").toMap(), m_session.revision());
        emit changed();
    }
}

void SailplayContentHost::select(const QString &id)
{
    for (const QVariant &item : m_items) {
        if (item.toMap().value("id").toString() == id) { invokeItem(item.toMap()); return; }
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
