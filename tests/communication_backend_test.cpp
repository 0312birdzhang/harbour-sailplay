#include "../display-source/communication/backend.h"
#include "sailplaysession.h"
#include "sailplaycontent.h"
#include <QCoreApplication>
#include <QDBusVirtualObject>
#include <QDBusMessage>
#include <QElapsedTimer>
#include <QDateTime>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QThread>
#include <QFile>
#include <QDir>
#include <QTemporaryDir>
#include <QJSValue>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <memory>

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "COMMUNICATION_CHECK_FAILED line=%d %s\n", __LINE__, #condition); std::exit(1); } } while (false)

bool waitFor(const std::function<bool()> &ready)
{
    QElapsedTimer elapsed;
    elapsed.start();
    while (!ready() && elapsed.elapsed() < 4000) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(1);
    }
    return ready();
}

class NativeService : public QDBusVirtualObject
{
public:
    int mutations = 0;
    bool reject = false;
    bool fail = false;
    QVariantList lastArguments;
    QString introspect(const QString &) const override { return QString(); }
    bool handleMessage(const QDBusMessage &message, const QDBusConnection &connection) override
    {
        if (message.member() == "GetAll") {
            connection.send(message.createReply(QVariantList{QVariantMap{{"providers", QStringList()}, {"isMicrophoneMuted", false}}}));
            return true;
        }
        ++mutations;
        lastArguments = message.arguments();
        QTimer::singleShot(100, this, [this, message, connection]() {
            if (fail) connection.send(message.createErrorReply("org.example.Failed", "mock failure"));
            else connection.send(message.createReply(message.member() == "dial" ? QVariantList{!reject} : QVariantList()));
        });
        return true;
    }
};

class MockModel : public QAbstractListModel
{
    Q_OBJECT
    Q_PROPERTY(bool populated READ populated NOTIFY populatedChanged)
    Q_PROPERTY(bool ready READ ready WRITE setReady NOTIFY modelReady)
    Q_PROPERTY(bool initialPending MEMBER m_initialPending)
    Q_PROPERTY(int filterType MEMBER filterType)
    Q_PROPERTY(int requiredProperty MEMBER requiredProperty)
    Q_PROPERTY(int limit MEMBER limit)
    Q_PROPERTY(bool useBackgroundThread MEMBER background)
    Q_PROPERTY(bool resolveContacts MEMBER resolve)
    Q_PROPERTY(QObject *manager MEMBER manager)
    Q_PROPERTY(int queryMode MEMBER queryMode)
    Q_PROPERTY(int groupId MEMBER groupId)
public:
    enum Option { FilterAll, PhoneNumberRequired, AsyncQuery, TemporarilyFailedStatus };
    Q_ENUMS(Option)
    int filterType = 0, requiredProperty = 0, limit = 0, queryMode = 0, groupId = 0;
    bool background = false, resolve = false;
    QObject *manager = nullptr;
    explicit MockModel(QObject *parent = nullptr) : QAbstractListModel(parent)
    {
        for (int id : {1, 2}) {
            QObject *group = new QObject(this);
            group->setProperty("id", id);
            group->setProperty("localUid", QStringLiteral("sms-account"));
            group->setProperty("remoteUids", QStringList{QStringLiteral("12345")});
            group->setProperty("lastMessageText", QStringLiteral("Example message"));
            group->setProperty("unreadMessages", 0);
            group->setProperty("endTime", QDateTime::currentDateTime());
            m_groups.append(group);
        }
    }
    bool populated() const { return true; }
    bool ready() const { return m_ready; }
    void setReady(bool value) { if (m_ready != value) { m_ready = value; emit modelReady(value); } }
    Q_INVOKABLE void completeInitialQuery()
    {
        beginResetModel();
        m_initialPending = false;
        endResetModel();
        emit modelReady(true);
    }
    Q_INVOKABLE void setLocalUid(int row, const QString &account) { m_groups[row]->setProperty("localUid", account); }
    int rowCount(const QModelIndex &parent = QModelIndex()) const override { return parent.isValid() || m_initialPending ? 0 : 2; }
    QHash<int, QByteArray> roleNames() const override
    {
        return {{1, "contactId"}, {2, "primaryName"}, {3, "secondaryName"}, {4, "phoneNumbers"},
            {5, "eventId"}, {6, "freeText"}, {7, "startTime"}, {8, "remoteUid"}, {9, "displayNames"}, {10, "groups"}};
    }
    QVariant data(const QModelIndex &index, int role) const override
    {
        const QString body = index.row() == 0 ? QString(999, QLatin1Char('a')) + QString::fromUtf8("\xF0\x9F\x98\x80") + QStringLiteral("tail")
                                             : QStringLiteral("Example message");
        const QVariantList values{index.row() + 1, QString("Alice"), QString("Example"),
            QStringList{"12345"}, index.row() + 7, body, QDateTime::fromMSecsSinceEpoch(1000), QString("12345"),
            QStringList{"Alice"}, QVariant::fromValue(QList<QObject *>{m_groups[index.row()]})};
        return values.value(role - 1);
    }
signals:
    void populatedChanged();
    void modelReady(bool successful);
private:
    bool m_ready = true;
    bool m_initialPending = false;
    QList<QObject *> m_groups;
};

void checkMessageModels(const QString &filename)
{
    QTemporaryDir imports;
    CHECK(imports.isValid());
    const auto write = [&](const QString &name, const QByteArray &data) {
        const QString path = imports.path() + '/' + name;
        CHECK(QDir().mkpath(QFileInfo(path).path()));
        QFile file(path);
        CHECK(file.open(QIODevice::WriteOnly) && file.write(data) == data.size());
    };
    qmlRegisterType<MockModel>("org.nemomobile.contacts", 1, 0, "PeopleModel");
    qmlRegisterType<MockModel>("org.nemomobile.commhistory", 1, 0, "CommCallModel");
    qmlRegisterType<MockModel>("org.nemomobile.commhistory", 1, 0, "CommContactGroupModel");
    qmlRegisterType<MockModel>("org.nemomobile.commhistory", 1, 0, "CommConversationModel");
    write("org/nemomobile/contacts/qmldir", "module org.nemomobile.contacts\n");
    write("org/nemomobile/voicecall/qmldir", "module org.nemomobile.voicecall\nVoiceCallManager 1.0 VoiceCallManager.qml\n");
    write("org/nemomobile/voicecall/VoiceCallManager.qml", "import QtQml 2.2\nQtObject { }\n");
    write("org/nemomobile/commhistory/qmldir", "module org.nemomobile.commhistory\nCommGroupManager 1.0 CommGroupManager.qml\n");
    // CommHistory is an enum namespace in the installed plugin.
    qmlRegisterUncreatableType<MockModel>("org.nemomobile.commhistory", 1, 0, "CommHistory", "enum namespace");
    write("org/nemomobile/commhistory/CommGroupManager.qml", R"QML(
import QtQml 2.2
QtObject {
    id: group
    property bool useBackgroundThread: false
    property bool resolveContacts: false
    property int creations: 0
    property int failedEvents: 0
    property var callback: null
    signal modelReady(bool successful)
    function createOutgoingMessageEvent(id, account, number, text, done) { creations++; callback = done }
    function completeEvent() { var done = callback; callback = null; done(42) }
    function setEventStatus(id, status) { failedEvents++ }
}
)QML");
    write("Sailfish/Messages/qmldir", "module Sailfish.Messages\nsingleton MessageUtils 1.0 MessageUtils.qml\n");
    write("Sailfish/Messages/MessageUtils.qml", R"QML(
pragma Singleton
import QtQml 2.2
QtObject {
    property bool messagingPermitted: true
    property string voiceModemPath: "/ril_0"
    property QtObject simManager: QtObject { property bool valid: true }
    property QtObject telepathyAccounts: QtObject {
        property bool ready: true
        property string ringAccountPath: "/org/freedesktop/Telepathy/Account/ring/tel/ril_0"
        property QtObject account: QtObject { property bool online: true }
        function getAccount(uid) { return account }
    }
    function isSMS(uid) { return uid.indexOf("/ring/tel") >= 0 }
}
)QML");
    write("Sailfish/Telephony/qmldir", "module Sailfish.Telephony\nSimErrorState 1.0 SimErrorState.qml\n");
    write("Sailfish/Telephony/SimErrorState.qml", "import QtQml 2.2\nQtObject { property var multiSimManager; property string modemPath; property bool valid: true; property string errorState: \"noSimInserted\" }\n");
    write("org/nemomobile/messages/internal/qmldir", "module org.nemomobile.messages.internal\nTelepathyChannelManager 1.0 TelepathyChannelManager.qml\n");
    write("org/nemomobile/messages/internal/TelepathyChannelManager.qml", R"QML(
import QtQml 2.2
QtObject {
    property string handlerName
    property QtObject channel: QtObject {
        property int sends: 0
        signal sendingSucceeded(int eventId, var sender)
        signal sendingFailed(int eventId, var sender)
        signal requestFailed(string errorName, string errorMessage)
        function sendMessage(text, eventId) { sends++ }
    }
    function getConversation(account, number) { return channel }
}
)QML");
    QQmlEngine engine;
    engine.addImportPath(imports.path());
    QQmlComponent component(&engine, QUrl::fromLocalFile(filename));
    std::unique_ptr<QObject> models(component.create());
    if (!models) fprintf(stderr, "%s\n", qPrintable(component.errorString()));
    CHECK(models);
    const auto call = [&](const char *method, const QVariant &argument) {
        QVariant result;
        CHECK(QMetaObject::invokeMethod(models.get(), method, Q_RETURN_ARG(QVariant, result), Q_ARG(QVariant, argument)));
        if (result.userType() == qMetaTypeId<QJSValue>()) return result.value<QJSValue>().toVariant();
        return result;
    };
    const QString account = "/org/freedesktop/Telepathy/Account/ring/tel/ril_0";
    const QVariantMap request{{"token", "test"}, {"account", account}, {"number", "12345"}, {"message", "Example"}};
    QObject *group = models->property("groupManager").value<QObject *>();
    CHECK(call("sendError", account).toString() == "NoSim");
    QObject *sim = models->property("simError").value<QObject *>();
    CHECK(!call("sendMessage", request).toBool() && group->property("creations").toInt() == 0);
    CHECK(call("sendError", "im-account").toString().isEmpty());
    for (const auto &entry : {qMakePair(QString("modemDisabled"), QString("DisabledSim")), qMakePair(QString("simActivationRequired"), QString("LockedSim"))}) {
        sim->setProperty("errorState", entry.first);
        CHECK(call("sendError", account).toString() == entry.second);
    }
    sim->setProperty("errorState", QString());
    CHECK(call("sendMessage", request).toBool());
    CHECK(!call("sendMessage", request).toBool());
    CHECK(QMetaObject::invokeMethod(group, "completeEvent"));
    QObject *channel = models->property("sendChannel").value<QObject *>();
    CHECK(channel && channel->property("sends").toInt() == 1);
    // A timeout after submission retains the guard until the definitive result.
    CHECK(QMetaObject::invokeMethod(models->property("sendTimer").value<QObject *>(), "triggered"));
    CHECK(models->property("messagePending").toBool());
    CHECK(QMetaObject::invokeMethod(channel, "sendingSucceeded", Q_ARG(int, 42), Q_ARG(QVariant, QVariant())));
    CHECK(!models->property("messagePending").toBool());
    CHECK(call("sendMessage", request).toBool());
    CHECK(QMetaObject::invokeMethod(group, "completeEvent"));
    channel = models->property("sendChannel").value<QObject *>();
    CHECK(QMetaObject::invokeMethod(channel, "sendingFailed", Q_ARG(int, 42), Q_ARG(QVariant, QVariant())));
    CHECK(!models->property("messagePending").toBool() && group->property("failedEvents").toInt() == 1);
    // A late history callback after a pre-submission timeout must never send.
    CHECK(call("sendMessage", request).toBool());
    CHECK(QMetaObject::invokeMethod(models->property("sendTimer").value<QObject *>(), "triggered"));
    CHECK(!models->property("messagePending").toBool());
    CHECK(QMetaObject::invokeMethod(group, "completeEvent"));
    CHECK(group->property("failedEvents").toInt() == 2);
    fprintf(stderr, "COMMUNICATION_MESSAGE_MODELS_PASS\n");
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    const QString kind = argc > 1 ? QString::fromLocal8Bit(argv[1]) : QStringLiteral("phone");
    QQmlEngine engine;
    qmlRegisterType<MockModel>("Test.Models", 1, 0, "MockModel");
    QQmlComponent component(&engine);
    component.setData(R"QML(
import QtQml 2.2
import Test.Models 1.0
QtObject {
    id: models
    signal contentChanged()
    signal messageFinished(string token, string error)
    property bool messagePending: false
    property string accountError: ""
    property bool sendFails: false
    property bool sendRejects: false
    property int sends: 0
    property var lastRequest: null
    property string sendToken: ""
    property Timer sendTimer: Timer {
        interval: 100
        onTriggered: {
            models.messagePending = false
            models.messageFinished(models.sendToken, models.sendFails ? "Failed" : "")
        }
    }
    property bool loading: false
    property QtObject contacts: MockModel { }
    property QtObject history: MockModel { }
    property QtObject groups: MockModel { }
    property Component conversationComponent: Component {
        MockModel {
            id: conversation
            initialPending: true
            ready: !models.loading
            property Timer startup: Timer {
                interval: 25
                running: true
                onTriggered: conversation.completeInitialQuery()
            }
        }
    }
    function createConversation(id) { return conversationComponent.createObject(models) }
    function smsAccount() { return "sms-account" }
    function sendError(account) { return account === "im-account" ? "" : accountError }
    function sendMessage(request) {
        if (sendRejects) return false
        sends += 1
        lastRequest = request
        sendToken = request.token
        messagePending = true
        sendTimer.start()
        return true
    }
    function calls() { return [] }
    function controlCall(id, action) { return id === "live" }
}
)QML", QUrl());
    std::unique_ptr<QObject> models(component.create());
    if (!models) fprintf(stderr, "%s\n", qPrintable(component.errorString()));
    CHECK(models);
    auto nativeBus = QDBusConnection::connectToBus(QDBusConnection::SessionBus, "communication-native");
    NativeService native;
    CHECK(nativeBus.registerService("com.jolla.voicecall.ui"));
    CHECK(nativeBus.registerService("org.nemomobile.voicecall"));
    CHECK(nativeBus.registerService("org.sailfishos.Messages"));
    CHECK(nativeBus.registerVirtualObject("/", &native));
    CommunicationBackend backend(kind, models.get());
    CHECK(backend.start());
    const QString service = "org.sailplay.System." + (kind == "phone" ? QString("Phone") : QString("Messages"));
    auto client = QDBusConnection::connectToBus(QDBusConnection::SessionBus, "communication-client");
    SailplaySession session(client), other(client);
    session.open(service);
    other.open(service);
    CHECK(waitFor([&]() { return session.ready() && other.ready(); }));
    QHash<qulonglong, QString> errors;
    QHash<qulonglong, QVariantMap> results;
    QObject::connect(&session, &SailplaySession::requestFinished, &app,
        [&](qulonglong id, qulonglong, const QVariantMap &result, const QString &error, const QString &) {
            errors.insert(id, error); results.insert(id, SailplayContent::decode(result).toMap());
        });
    const QString action = kind == "phone" ? "phone.dial" : "messages.send";
    const QVariantMap parameters = kind == "phone" ? QVariantMap{{"number", "12345"}}
        : QVariantMap{{"number", "12345"}, {"message", "Example"}};
    const auto invoke = [&](const QString &name, const QVariantMap &values) {
        const qulonglong id = session.invoke(name, values);
        CHECK(id && waitFor([&]() { return errors.contains(id); }));
        return id;
    };
    session.setActive(false);
    CHECK(!errors.value(invoke(action, parameters)).isEmpty());
    CHECK(native.mutations == 0);
    session.setActive(true);
    const qulonglong stale = session.invoke("content.browse", {{"id", "root"}, {"offset", uint(0)}, {"limit", uint(1)}}, session.revision() + 1);
    CHECK(waitFor([&]() { return errors.contains(stale); }));
    CHECK(errors.value(stale).endsWith("StaleRevision"));
    const qulonglong browse = invoke("content.browse", {{"id", kind == "phone" ? "contacts" : "thread:1"},
        {"offset", uint(0)}, {"limit", uint(1)}});
    CHECK(errors.value(browse).isEmpty());
    CHECK(results.value(browse).value("content").toMap().value("items").toList().size() == 1);
    CHECK(results.value(browse).value("content").toMap().value("hasMore").toBool());
    CHECK(!errors.value(invoke(action, {{"number", "bad"}})).isEmpty());
    CHECK(native.mutations == 0);
    if (kind == "messages") {
        for (const QString &error : {QString("NoSim"), QString("LockedSim"), QString("DisabledSim"), QString("Unavailable"), QString("Forbidden")}) {
            models->setProperty("accountError", error);
            CHECK(errors.value(invoke(action, parameters)).endsWith(error));
            CHECK(models->property("sends").toInt() == 0 && native.mutations == 0);
        }
        models->setProperty("accountError", QString());
    }
    const qulonglong first = session.invoke(action, parameters);
    const qulonglong second = session.invoke(action, parameters);
    CHECK(waitFor([&]() { return errors.contains(first) && errors.contains(second); }));
    CHECK(errors.value(first).isEmpty() && errors.value(second).endsWith("Busy"));
    CHECK(kind == "phone" ? native.mutations == 1 : native.mutations == 0 && models->property("sends").toInt() == 1);
    native.fail = true; models->setProperty("sendFails", true);
    CHECK(errors.value(invoke(action, parameters)).endsWith("Failed"));
    native.fail = false; models->setProperty("sendFails", false);
    if (kind == "phone") {
        const qulonglong history = invoke("content.browse", {{"id", "history"}, {"offset", uint(0)}, {"limit", uint(50)}});
        const QVariantList calls = results.value(history).value("content").toMap().value("items").toList();
        CHECK(errors.value(history).isEmpty() && calls.size() == 2 && calls[0].toMap().value("id") != calls[1].toMap().value("id"));
        CHECK(errors.value(invoke("content.browse", {{"id", "history:999"}, {"offset", uint(0)}, {"limit", uint(50)}})).endsWith("NotFound"));
        native.reject = true;
        CHECK(errors.value(invoke(action, parameters)).endsWith("Failed"));
        CHECK(errors.value(invoke("phone.hangup", {{"id", "missing"}})).endsWith("NotFound"));
        CHECK(errors.value(invoke("phone.answer", {{"id", "live"}})).isEmpty());
    } else {
        models->setProperty("sendRejects", true);
        CHECK(errors.value(invoke(action, parameters)).endsWith("Unavailable"));
        models->setProperty("sendRejects", false);
        const qulonglong pending = session.invoke(action, parameters);
        CHECK(waitFor([&]() { return models->property("messagePending").toBool(); }));
        QMetaObject::invokeMethod(models.get(), "messageFinished", Q_ARG(QString, QString("unrelated")), Q_ARG(QString, QString()));
        CHECK(!errors.contains(pending));
        const QString token = models->property("sendToken").toString();
        QMetaObject::invokeMethod(models.get(), "messageFinished", Q_ARG(QString, token), Q_ARG(QString, QString("TimedOut")));
        CHECK(waitFor([&]() { return errors.contains(pending); }) && errors.value(pending).endsWith("TimedOut"));
        CHECK(errors.value(invoke(action, parameters)).endsWith("Busy"));
        CHECK(waitFor([&]() { return !models->property("messagePending").toBool(); }));
        CHECK(errors.value(invoke(action, parameters)).isEmpty());
        QObject *groups = models->property("groups").value<QObject *>();
        const QString oldSms = "/org/freedesktop/Telepathy/Account/ring/tel/old_modem";
        CHECK(QMetaObject::invokeMethod(groups, "setLocalUid", Q_ARG(int, 0), Q_ARG(QString, oldSms)));
        CHECK(errors.value(invoke(action, {{"number", "12345"}, {"message", "Reply"}, {"account", oldSms}})).isEmpty());
        CHECK(models->property("lastRequest").value<QJSValue>().property("account").toString() == "sms-account");
        CHECK(QMetaObject::invokeMethod(groups, "setLocalUid", Q_ARG(int, 0), Q_ARG(QString, QString("sms-account"))));
        CHECK(QMetaObject::invokeMethod(groups, "setLocalUid", Q_ARG(int, 1), Q_ARG(QString, QString("im-account"))));
        models->setProperty("accountError", QString("NoSim"));
        CHECK(errors.value(invoke(action, {{"number", "12345"}, {"message", "Reply"}, {"account", "im-account"}})).isEmpty());
        CHECK(models->property("lastRequest").value<QJSValue>().property("account").toString() == "im-account");
        models->setProperty("accountError", QString());
        const qulonglong conversation = invoke("content.browse", {{"id", "thread:1"}, {"offset", uint(0)}, {"limit", uint(50)}});
        const QVariantList messages = results.value(conversation).value("content").toMap().value("items").toList();
        CHECK(errors.value(conversation).isEmpty() && messages.size() == 3);
        CHECK(messages[0].toMap().value("title").toString() + messages[1].toMap().value("title").toString()
            == QString(999, QLatin1Char('a')) + QString::fromUtf8("\xF0\x9F\x98\x80") + QStringLiteral("tail"));
        QVariantList paginated;
        for (uint offset = 0; offset < 3; ++offset) {
            const qulonglong page = invoke("content.browse", {{"id", "thread:1"}, {"offset", offset}, {"limit", uint(1)}});
            const QVariantMap content = results.value(page).value("content").toMap();
            CHECK(errors.value(page).isEmpty() && content.value("items").toList().size() == 1);
            CHECK(content.value("hasMore").toBool() == (offset < 2));
            paginated.append(content.value("items").toList());
        }
        CHECK(paginated == messages);
        models->setProperty("loading", true);
        const QVariantMap query{{"id", "thread:1"}, {"offset", uint(0)}, {"limit", uint(1)}};
        const qulonglong loading = session.invoke("content.browse", query);
        const qulonglong concurrent = session.invoke("content.browse", query);
        CHECK(waitFor([&]() { return errors.contains(concurrent); }));
        CHECK(errors.value(concurrent).endsWith("Busy") && !errors.contains(loading));
        models->setProperty("loading", false);
        CHECK(waitFor([&]() { return errors.contains(loading); }) && errors.value(loading).isEmpty());
        const qulonglong recipient = invoke("messages.recipient", {{"id", "thread:1"}});
        CHECK(errors.value(recipient).isEmpty() && results.value(recipient).value("number") == "12345");
        CHECK(errors.value(invoke(action, {{"number", "12345"}, {"message", "Reply"}, {"account", "obsolete"}})).endsWith("NotFound"));
    }
    session.close(); other.close();
    if (kind == "messages" && argc > 2) checkMessageModels(QString::fromLocal8Bit(argv[2]));
    fprintf(stderr, "COMMUNICATION_BACKEND_PASS %s\n", qPrintable(kind));
    return 0;
}

#include "communication_backend_test.moc"
