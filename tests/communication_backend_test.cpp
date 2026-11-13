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
    Q_PROPERTY(bool populated READ populated CONSTANT)
    Q_PROPERTY(bool ready READ ready WRITE setReady NOTIFY modelReady)
    Q_PROPERTY(bool initialPending MEMBER m_initialPending)
public:
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
    void modelReady(bool successful);
private:
    bool m_ready = true;
    bool m_initialPending = false;
    QList<QObject *> m_groups;
};

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
    const qulonglong first = session.invoke(action, parameters);
    const qulonglong second = session.invoke(action, parameters);
    CHECK(waitFor([&]() { return errors.contains(first) && errors.contains(second); }));
    CHECK(errors.value(first).isEmpty() && errors.value(second).endsWith("Busy"));
    CHECK(native.mutations == 1);
    native.fail = true;
    CHECK(errors.value(invoke(action, parameters)).endsWith("Failed"));
    native.fail = false;
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
    fprintf(stderr, "COMMUNICATION_BACKEND_PASS %s\n", qPrintable(kind));
    return 0;
}

#include "communication_backend_test.moc"
