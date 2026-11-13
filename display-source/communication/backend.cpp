#include "backend.h"
#include "sailplaycontent.h"
#include <QCoreApplication>
#include <QDateTime>
#include <QDBusArgument>
#include <QDBusConnectionInterface>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusVariant>
#include <QJSValue>
#include <QRegExp>
#include <QVector>
#include <algorithm>

namespace {
QString text(const char *source)
{
    return QCoreApplication::translate("Sailplay", source);
}

QVariant role(QAbstractItemModel *model, int row, const QByteArray &name)
{
    if (!model) return QVariant();
    const auto roles = model->roleNames();
    return model->data(model->index(row, 0), roles.key(name, -1));
}

QString bounded(const QString &value)
{
    const QVector<uint> characters = QString(value).remove(QChar::Null).toUcs4();
    return QString::fromUcs4(characters.constData(), qMin(1024, characters.size()));
}

QVariantMap folder(const QString &id, const QString &title, const QString &subtitle = QString())
{
    QVariantMap item = SailplayContent::item(id, bounded(title.isEmpty() ? text("Unknown") : title));
    item[QStringLiteral("subtitle")] = bounded(subtitle);
    return item;
}

QVariantMap actionItem(const QString &id, const QString &title, const QString &action, const QVariantMap &parameters)
{
    return SailplayContent::item(id, bounded(title), QStringLiteral("action"), action, parameters);
}

QVariantMap paged(const QString &id, const QString &title, const QVariantList &rows,
                  const QVariantMap &parameters, qulonglong version)
{
    QVariantMap page = SailplayContent::page(id, bounded(title));
    const uint offset = parameters.value(QStringLiteral("offset")).toUInt();
    const uint limit = parameters.value(QStringLiteral("limit")).toUInt();
    QVariantList items;
    const uint end = qMin(uint(rows.size()), offset + limit);
    for (uint i = offset; i < end; ++i) items.append(rows.at(int(i)));
    page[QStringLiteral("items")] = items;
    page[QStringLiteral("offset")] = offset;
    page[QStringLiteral("hasMore")] = end < uint(rows.size()) && !items.isEmpty();
    page[QStringLiteral("version")] = version;
    page[QStringLiteral("searchEnabled")] = true;
    return page;
}

bool fields(const QVariantMap &parameters, const QStringList &expected)
{
    return QSet<QString>::fromList(parameters.keys()) == QSet<QString>::fromList(expected);
}

bool number(const QVariant &value)
{
    return value.type() == QVariant::String
        && QRegExp(QStringLiteral("[+0-9*#][+0-9*#() .-]{0,63}")).exactMatch(value.toString());
}
}

CommunicationBackend::CommunicationBackend(const QString &kind, QObject *models, QObject *parent)
    : QObject(parent), m_kind(kind), m_models(models)
{
    m_state.insert(QStringLiteral("content"), rootPage());
    m_provider = new SailplayProvider(QStringLiteral("sailplay-") + kind, m_state,
        QStringList() << QStringLiteral("content") << kind, this);
    for (const QString &name : {QStringLiteral("content.browse"), QStringLiteral("content.search")}) {
        m_provider->setActionHandler(name, [this, name](qulonglong invocation, const QVariantMap &parameters) {
            browse(invocation, parameters, name.endsWith(QStringLiteral("search")));
        });
    }
    const QStringList actions = kind == QStringLiteral("phone")
        ? QStringList() << QStringLiteral("phone.dial") << QStringLiteral("phone.answer")
                        << QStringLiteral("phone.hangup") << QStringLiteral("phone.mute")
        : QStringList() << QStringLiteral("messages.send");
    for (const QString &action : actions) {
        m_provider->setActionHandler(action, [this, action](qulonglong invocation, const QVariantMap &parameters) {
            mutate(invocation, action, parameters);
        });
    }
    if (kind == QStringLiteral("messages")) {
        m_provider->setActionHandler(QStringLiteral("messages.recipient"), [this](qulonglong invocation, const QVariantMap &parameters) {
            if (!fields(parameters, {QStringLiteral("id")})) {
                m_provider->fail(invocation, QStringLiteral("InvalidArgument"), text("Invalid content request")); return;
            }
            for (const QVariant &entry : threads()) {
                const QVariantMap thread = entry.toMap();
                if (parameters.value(QStringLiteral("id")).toString() != QStringLiteral("thread:%1").arg(thread.value(QStringLiteral("id")).toInt())) continue;
                const QStringList recipients = thread.value(QStringLiteral("remoteUids")).toStringList();
                if (recipients.size() != 1 || !number(recipients.first())) break;
                m_provider->complete(invocation, {{QStringLiteral("number"), recipients.first()},
                    {QStringLiteral("account"), thread.value(QStringLiteral("localUid"))}}); return;
            }
            m_provider->fail(invocation, QStringLiteral("NotSupported"), text("Choose one SMS recipient"));
        });
    }
    connect(models, SIGNAL(contentChanged()), this, SLOT(invalidate()));
    for (const char *name : {"contacts", "history", "groups"}) {
        QAbstractItemModel *model = qobject_cast<QAbstractItemModel *>(models->property(name).value<QObject *>());
        if (!model) continue;
        connect(model, &QAbstractItemModel::dataChanged, this, &CommunicationBackend::invalidate);
        connect(model, &QAbstractItemModel::rowsInserted, this, &CommunicationBackend::invalidate);
        connect(model, &QAbstractItemModel::rowsRemoved, this, &CommunicationBackend::invalidate);
        connect(model, &QAbstractItemModel::modelReset, this, &CommunicationBackend::invalidate);
    }
    m_contentTimer.setSingleShot(true);
    m_contentTimer.setInterval(150);
    connect(&m_contentTimer, &QTimer::timeout, this, [this]() { ++m_contentVersion; refresh(); });
    m_poll.setInterval(1000);
    connect(&m_poll, &QTimer::timeout, this, &CommunicationBackend::refresh);
    m_idle.setSingleShot(true);
    m_idle.setInterval(30000);
    connect(&m_idle, &QTimer::timeout, QCoreApplication::instance(), &QCoreApplication::quit);
    connect(m_provider, &SailplayProvider::sessionsChanged, this, [this]() {
        if (m_provider->sessionCount()) m_idle.stop(); else m_idle.start();
        if (m_provider->activeSessionCount()) { m_poll.start(); refresh(); } else m_poll.stop();
    });
    m_queryTimer.setSingleShot(true);
    m_queryTimer.setInterval(8000);
    connect(&m_queryTimer, &QTimer::timeout, this, [this]() { conversationReady(false); });
}

bool CommunicationBackend::start()
{
    const QString service = QStringLiteral("org.sailplay.System.")
        + (m_kind == QStringLiteral("phone") ? QStringLiteral("Phone") : QStringLiteral("Messages"));
    if (!QDBusConnection::sessionBus().registerService(service) || !m_provider->start()) return false;
    m_idle.start();
    refresh();
    return true;
}

QVariant CommunicationBackend::callModels(const char *method, const QVariantList &arguments) const
{
    QVariant result;
    bool invoked = false;
    if (arguments.isEmpty()) invoked = QMetaObject::invokeMethod(m_models, method, Q_RETURN_ARG(QVariant, result));
    else if (arguments.size() == 1) invoked = QMetaObject::invokeMethod(m_models, method,
        Q_RETURN_ARG(QVariant, result), Q_ARG(QVariant, arguments[0]));
    else if (arguments.size() == 2) invoked = QMetaObject::invokeMethod(m_models, method,
        Q_RETURN_ARG(QVariant, result), Q_ARG(QVariant, arguments[0]), Q_ARG(QVariant, arguments[1]));
    if (!invoked) return QVariant();
    if (result.userType() != qMetaTypeId<QJSValue>()) return result;
    const QJSValue value = result.value<QJSValue>();
    return value.isQObject() ? QVariant::fromValue(value.toQObject()) : value.toVariant();
}

QVariantList CommunicationBackend::threads() const
{
    // Read model-owned grouping objects through native roles to retain their ownership.
    auto *model = qobject_cast<QAbstractItemModel *>(m_models->property("groups").value<QObject *>());
    QVariantList rows;
    for (int row = 0; model && row < model->rowCount(); ++row) {
        const QString names = role(model, row, "displayNames").toStringList().join(QStringLiteral(", "));
        const QList<QObject *> groups = role(model, row, "groups").value<QList<QObject *>>();
        for (QObject *group : groups) {
            const QStringList recipients = group->property("remoteUids").toStringList();
            rows.append(QVariantMap{{QStringLiteral("id"), group->property("id")},
                {QStringLiteral("name"), names.isEmpty() ? recipients.join(QStringLiteral(", ")) : names},
                {QStringLiteral("localUid"), group->property("localUid")}, {QStringLiteral("remoteUids"), recipients},
                {QStringLiteral("text"), group->property("lastMessageText")},
                {QStringLiteral("unread"), group->property("unreadMessages")},
                {QStringLiteral("time"), group->property("endTime").toDateTime().toUTC().toString(Qt::ISODate)}});
        }
    }
    std::sort(rows.begin(), rows.end(), [](const QVariant &first, const QVariant &second) {
        return first.toMap().value(QStringLiteral("time")).toString() > second.toMap().value(QStringLiteral("time")).toString();
    });
    return rows;
}

QVariantMap CommunicationBackend::rootPage() const
{
    QVariantMap page = SailplayContent::page(QStringLiteral("root"), text(m_kind == QStringLiteral("phone") ? "Phone" : "Messages"));
    page[QStringLiteral("version")] = m_contentVersion;
    page[QStringLiteral("searchEnabled")] = true;
    if (m_kind == QStringLiteral("phone")) {
        page[QStringLiteral("items")] = QVariantList()
            << folder(QStringLiteral("contacts"), text("Contacts"))
            << folder(QStringLiteral("history"), text("Recent calls"));
    } else {
        QVariantList items;
        const QVariantList available = threads();
        for (const QVariant &entry : available.mid(0, 40)) {
            const QVariantMap thread = entry.toMap();
            items.append(folder(QStringLiteral("thread:%1").arg(thread.value(QStringLiteral("id")).toInt()),
                thread.value(QStringLiteral("name")).toString(), thread.value(QStringLiteral("text")).toString()));
        }
        page[QStringLiteral("items")] = items;
        page[QStringLiteral("hasMore")] = available.size() > items.size();
    }
    return page;
}

void CommunicationBackend::invalidate() { if (!m_contentTimer.isActive()) m_contentTimer.start(); }

void CommunicationBackend::refresh()
{
    QVariantMap state = m_state;
    state[QStringLiteral("content")] = rootPage();
    if (m_kind == QStringLiteral("messages")) state[QStringLiteral("smsAccount")] = callModels("smsAccount").toString();
    if (m_kind == QStringLiteral("phone")) {
        QDBusMessage request = QDBusMessage::createMethodCall(QStringLiteral("org.nemomobile.voicecall"),
            QStringLiteral("/"), QStringLiteral("org.freedesktop.DBus.Properties"), QStringLiteral("GetAll"));
        request << QStringLiteral("org.nemomobile.voicecall.VoiceCallManager");
        const QDBusMessage reply = QDBusConnection::sessionBus().call(request, QDBus::Block, 500);
        const QVariantMap properties = reply.type() == QDBusMessage::ReplyMessage
            ? qdbus_cast<QVariantMap>(reply.arguments().value(0)) : QVariantMap();
        state[QStringLiteral("providers")] = properties.value(QStringLiteral("providers")).toStringList();
        state[QStringLiteral("muted")] = properties.value(QStringLiteral("isMicrophoneMuted"), false).toBool();
        state[QStringLiteral("calls")] = callModels("calls").toList();
    }
    if (state == m_state) return;
    if (m_provider->publish(state)) m_state = state;
}

void CommunicationBackend::browse(qulonglong invocation, const QVariantMap &parameters, bool search)
{
    if (!SailplayContent::validQuery(parameters, search)) {
        m_provider->fail(invocation, QStringLiteral("InvalidArgument"), text("Invalid content request")); return;
    }
    const QString id = parameters.value(QStringLiteral("id")).toString();
    const QString query = search ? parameters.value(QStringLiteral("query")).toString() : QString();
    QVariantList rows;
    QString title;
    if (m_kind == QStringLiteral("phone")) {
        if (id == QStringLiteral("root") && query.isEmpty()) rows = rootPage().value(QStringLiteral("items")).toList();
        else if (id == QStringLiteral("contacts") || id == QStringLiteral("root")) {
            title = text("Contacts");
            auto *model = qobject_cast<QAbstractItemModel *>(m_models->property("contacts").value<QObject *>());
            if (!model || !model->property("populated").toBool()) {
                m_provider->fail(invocation, QStringLiteral("Unavailable"), text("Contacts are loading")); return;
            }
            for (int row = 0; row < model->rowCount(); ++row) {
                const QString name = (role(model, row, "primaryName").toString() + QLatin1Char(' ')
                    + role(model, row, "secondaryName").toString()).trimmed();
                const QStringList numbers = role(model, row, "phoneNumbers").toStringList();
                if (numbers.isEmpty() || (!name.contains(query, Qt::CaseInsensitive)
                    && !numbers.join(QLatin1Char(' ')).contains(query))) continue;
                rows.append(folder(QStringLiteral("contact:%1").arg(role(model, row, "contactId").toInt()), name, numbers.first()));
            }
        } else if (id == QStringLiteral("history")) {
            title = text("Recent calls");
            auto *model = qobject_cast<QAbstractItemModel *>(m_models->property("history").value<QObject *>());
            for (int row = 0; model && row < model->rowCount(); ++row) {
                const QString remote = role(model, row, "remoteUid").toString();
                if (!remote.contains(query)) continue;
                const QString identity = QStringLiteral("history:%1").arg(role(model, row, "eventId").toInt());
                rows.append(folder(identity, remote, role(model, row, "startTime").toDateTime().toString(Qt::DefaultLocaleShortDate)));
            }
        } else if (id.startsWith(QStringLiteral("contact:")) || id.startsWith(QStringLiteral("history:"))) {
            QStringList numbers;
            title = text("Call");
            if (id.startsWith(QStringLiteral("history:"))) {
                auto *model = qobject_cast<QAbstractItemModel *>(m_models->property("history").value<QObject *>());
                bool valid = false;
                const int eventId = id.mid(8).toInt(&valid);
                for (int row = 0; valid && model && row < model->rowCount(); ++row) {
                    if (role(model, row, "eventId").toInt() == eventId) {
                        numbers << role(model, row, "remoteUid").toString(); break;
                    }
                }
            } else {
                auto *model = qobject_cast<QAbstractItemModel *>(m_models->property("contacts").value<QObject *>());
                const int contactId = id.mid(8).toInt();
                for (int row = 0; model && row < model->rowCount(); ++row) {
                    if (role(model, row, "contactId").toInt() == contactId) {
                        numbers = role(model, row, "phoneNumbers").toStringList();
                        title = role(model, row, "primaryName").toString(); break;
                    }
                }
            }
            if (numbers.isEmpty()) {
                m_provider->fail(invocation, QStringLiteral("NotFound"), text("Selection is no longer available")); return;
            }
            for (int i = 0; i < numbers.size(); ++i)
                rows.append(actionItem(QString::number(i), numbers[i], QStringLiteral("phone.dial"), {{QStringLiteral("number"), numbers[i]}}));
        } else {
            m_provider->fail(invocation, QStringLiteral("NotFound"), text("Selection is no longer available")); return;
        }
    } else {
        const QVariantList available = threads();
        if (id == QStringLiteral("root")) {
            title = text("Messages");
            for (const QVariant &entry : available) {
                const QVariantMap thread = entry.toMap();
                const QString name = thread.value(QStringLiteral("name")).toString();
                const QString message = thread.value(QStringLiteral("text")).toString();
                if (!name.contains(query, Qt::CaseInsensitive) && !message.contains(query, Qt::CaseInsensitive)) continue;
                rows.append(folder(QStringLiteral("thread:%1").arg(thread.value(QStringLiteral("id")).toInt()), name, message));
            }
        } else if (id.startsWith(QStringLiteral("thread:"))) {
            bool valid = false;
            const int group = id.mid(7).toInt(&valid);
            QVariantMap selected;
            for (const QVariant &entry : available) {
                if (entry.toMap().value(QStringLiteral("id")).toInt() == group) selected = entry.toMap();
            }
            if (!valid || selected.isEmpty()) {
                m_provider->fail(invocation, QStringLiteral("NotFound"), text("Selection is no longer available")); return;
            }
            if (m_query) { m_provider->fail(invocation, QStringLiteral("Busy"), text("A conversation is loading")); return; }
            if (m_group != group || !m_conversation) {
                delete m_conversation;
                m_conversationLoaded = false;
                m_conversation = qobject_cast<QAbstractItemModel *>(callModels("createConversation", {group}).value<QObject *>());
                m_group = group;
                if (m_conversation) {
                    connect(m_conversation, SIGNAL(modelReady(bool)), this, SLOT(conversationReady(bool)));
                    // Initial query population belongs to the current request's content version.
                    auto changed = [this]() { if (m_conversationLoaded) invalidate(); };
                    connect(m_conversation, &QAbstractItemModel::dataChanged, this, changed);
                    connect(m_conversation, &QAbstractItemModel::rowsInserted, this, changed);
                    connect(m_conversation, &QAbstractItemModel::rowsRemoved, this, changed);
                }
            }
            if (!m_conversation) { m_provider->fail(invocation, QStringLiteral("Unavailable"), text("Could not load conversation")); return; }
            m_query = invocation;
            m_queryVersion = m_contentVersion;
            m_parameters = parameters;
            m_threadTitle = selected.value(QStringLiteral("name")).toString();
            if (m_conversationLoaded && m_conversation->property("ready").toBool()) finishConversation(); else m_queryTimer.start();
            return;
        } else { m_provider->fail(invocation, QStringLiteral("NotFound"), text("Selection is no longer available")); return; }
    }
    if (title.isEmpty()) title = text("Phone");
    if (!m_provider->complete(invocation, {{QStringLiteral("content"), paged(id, title, rows, parameters, m_contentVersion)}}))
        m_provider->fail(invocation, QStringLiteral("Unavailable"), text("Invalid content request"));
}

void CommunicationBackend::conversationReady(bool successful)
{
    m_conversationLoaded = successful;
    if (!m_query) return;
    if (successful) { finishConversation(); return; }
    m_queryTimer.stop();
    m_provider->fail(m_query, QStringLiteral("Unavailable"), text("Could not load conversation"));
    m_query = 0;
    m_group = -1;
    disconnect(m_conversation, nullptr, this, nullptr);
    m_conversation->deleteLater(); m_conversation = nullptr;
}

void CommunicationBackend::finishConversation()
{
    m_queryTimer.stop();
    if (m_queryVersion != m_contentVersion) {
        m_provider->fail(m_query, QStringLiteral("Conflict"), text("Content changed. Refresh and try again."));
        m_query = 0;
        return;
    }
    QVariantList rows;
    for (int row = 0; row < m_conversation->rowCount(); ++row) {
        const QString body = role(m_conversation, row, "freeText").toString().remove(QChar::Null);
        const QString message = body.isEmpty() ? text("Attachment") : body;
        const QVector<uint> characters = message.toUcs4();
        for (int offset = 0; offset < characters.size(); offset += 1000) {
            QVariantMap item = actionItem(QStringLiteral("%1:%2").arg(role(m_conversation, row, "eventId").toInt()).arg(offset),
                QString::fromUcs4(characters.constData() + offset, qMin(1000, characters.size() - offset)),
                QStringLiteral("messages.view"), QVariantMap());
            item[QStringLiteral("enabled")] = false;
            item[QStringLiteral("subtitle")] = role(m_conversation, row, "startTime").toDateTime().toString(Qt::DefaultLocaleShortDate);
            rows.append(item);
        }
    }
    QVariantMap page = paged(m_parameters.value(QStringLiteral("id")).toString(), m_threadTitle, rows, m_parameters, m_contentVersion);
    page[QStringLiteral("searchEnabled")] = false;
    if (!m_provider->complete(m_query, {{QStringLiteral("content"), page}}))
        m_provider->fail(m_query, QStringLiteral("Unavailable"), text("Could not load conversation"));
    m_query = 0;
}

void CommunicationBackend::systemCall(qulonglong invocation, const QString &service, const QString &path,
    const QString &interface, const QString &method, const QVariantList &arguments)
{
    QDBusMessage request = QDBusMessage::createMethodCall(service, path, interface, method);
    request.setArguments(arguments);
    m_mutationPending = true;
    auto *watcher = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(request, 15000), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, watcher, invocation]() {
        m_mutationPending = false;
        const QDBusMessage reply = watcher->reply();
        if (reply.type() == QDBusMessage::ErrorMessage)
            m_provider->fail(invocation, QStringLiteral("Failed"), reply.errorMessage());
        else if (!reply.arguments().isEmpty() && reply.arguments().first().type() == QVariant::Bool && !reply.arguments().first().toBool())
            m_provider->fail(invocation, QStringLiteral("Failed"), text("The system service rejected the request"));
        else m_provider->complete(invocation, {{QStringLiteral("submitted"), true}});
        watcher->deleteLater(); refresh();
    });
}

void CommunicationBackend::mutate(qulonglong invocation, const QString &action, const QVariantMap &parameters)
{
    if (!m_provider->invocationActive(invocation)) {
        m_provider->fail(invocation, QStringLiteral("Unavailable"), text("The car app is inactive")); return;
    }
    if (m_mutationPending) { m_provider->fail(invocation, QStringLiteral("Busy"), text("A request is already in progress")); return; }
    if (action == QStringLiteral("phone.dial")) {
        if (!fields(parameters, {QStringLiteral("number")}) || !number(parameters.value(QStringLiteral("number")))) {
            m_provider->fail(invocation, QStringLiteral("InvalidArgument"), text("Enter a valid phone number")); return;
        }
        systemCall(invocation, QStringLiteral("com.jolla.voicecall.ui"), QStringLiteral("/"),
            QStringLiteral("com.jolla.voicecall.ui"), QStringLiteral("dial"), {parameters.value(QStringLiteral("number"))});
    } else if (action == QStringLiteral("phone.answer") || action == QStringLiteral("phone.hangup")) {
        if (!fields(parameters, {QStringLiteral("id")}) || parameters.value(QStringLiteral("id")).type() != QVariant::String
            || !callModels("controlCall", {parameters.value(QStringLiteral("id")), action.mid(6)}).toBool())
            m_provider->fail(invocation, QStringLiteral("NotFound"), text("The call is no longer available"));
        else m_provider->complete(invocation, {{QStringLiteral("submitted"), true}});
    } else if (action == QStringLiteral("phone.mute")) {
        if (!fields(parameters, {QStringLiteral("muted")}) || parameters.value(QStringLiteral("muted")).type() != QVariant::Bool) {
            m_provider->fail(invocation, QStringLiteral("InvalidArgument"), text("Invalid call control")); return;
        }
        systemCall(invocation, QStringLiteral("org.nemomobile.voicecall"), QStringLiteral("/"),
            QStringLiteral("org.nemomobile.voicecall.VoiceCallManager"), QStringLiteral("setMuteMicrophone"), {parameters.value(QStringLiteral("muted"))});
    } else if (action == QStringLiteral("messages.send")) {
        QString account = callModels("smsAccount").toString();
        if (parameters.contains(QStringLiteral("account")) && !parameters.value(QStringLiteral("account")).toString().isEmpty()) {
            bool matched = false;
            for (const QVariant &entry : threads()) {
                const QVariantMap thread = entry.toMap();
                if (thread.value(QStringLiteral("localUid")) == parameters.value(QStringLiteral("account"))
                    && thread.value(QStringLiteral("remoteUids")).toStringList().contains(parameters.value(QStringLiteral("number")).toString())) matched = true;
            }
            if (!matched) { m_provider->fail(invocation, QStringLiteral("NotFound"), text("Selection is no longer available")); return; }
            account = parameters.value(QStringLiteral("account")).toString();
        }
        const QVariant body = parameters.value(QStringLiteral("message"));
        const bool validFields = fields(parameters, {QStringLiteral("number"), QStringLiteral("message")})
            || fields(parameters, {QStringLiteral("number"), QStringLiteral("message"), QStringLiteral("account")});
        if (!validFields || account.isEmpty()
            || !number(parameters.value(QStringLiteral("number"))) || body.type() != QVariant::String
            || body.toString().trimmed().isEmpty() || body.toString().size() > 4096 || body.toString().contains(QChar::Null)) {
            m_provider->fail(invocation, QStringLiteral("InvalidArgument"), text("Enter a recipient and message")); return;
        }
        systemCall(invocation, QStringLiteral("org.sailfishos.Messages"), QStringLiteral("/"),
            QStringLiteral("org.sailfishos.Messages"), QStringLiteral("sendMessage"),
            {account, parameters.value(QStringLiteral("number")), body});
    }
}
