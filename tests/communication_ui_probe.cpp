#include "../display-source/carui/themesettings.h"
#include <QFile>
#include <QCryptographicHash>
#include <QGuiApplication>
#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickRenderControl>
#include <QQuickWindow>
#include <QTemporaryDir>
#include <QTest>
#include <cstdio>
#include <memory>
#include <stdexcept>

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "COMMUNICATION_UI_FAILED line=%d %s\n", __LINE__, #condition); throw std::runtime_error("UI check failed"); } } while (false)

QList<QQuickItem *> itemsNamed(QQuickItem *root, const QString &name)
{
    QList<QQuickItem *> items;
    if (root->objectName() == name) items.append(root);
    for (QQuickItem *child : root->childItems()) items.append(itemsNamed(child, name));
    return items;
}

void settle(QQuickRenderControl &layout)
{
    for (int pass = 0; pass < 4; ++pass) {
        QTest::qWait(20);
        layout.polishItems();
    }
}

void checkTextBounds(QQuickItem *row)
{
    for (QQuickItem *child : row->childItems()) {
        if (!child->isVisible()) continue;
        if (child->inherits("QQuickText")) {
            const QPointF point = child->mapToItem(row, QPointF());
            CHECK(point.y() >= -1 && point.y() + child->height() <= row->height() + 1);
        }
        for (QQuickItem *text : child->childItems()) {
            if (!text->isVisible() || !text->inherits("QQuickText")) continue;
            const QPointF point = text->mapToItem(row, QPointF());
            CHECK(point.y() >= -1 && point.y() + text->height() <= row->height() + 1);
            CHECK(text->property("lineCount").toInt() == 1);
        }
    }
}

int runProbe(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    CHECK(argc >= 2);
    QTemporaryDir home;
    CHECK(home.isValid());
    qputenv("HOME", home.path().toUtf8());
    QDir().mkpath(QFileInfo(SailplayThemeSettings::configPath()).absolutePath());
    QSettings settings(SailplayThemeSettings::configPath(), QSettings::IniFormat);
    settings.setValue("FollowAmbience", false);
    settings.setValue("DayStart", "00:00");
    settings.setValue("NightStart", "00:00");
    settings.sync();
    SailplayThemeSettings theme;
    CHECK(theme.update() && !theme.dayTheme());
    CHECK(!theme.update());
    const int minute = QTime::currentTime().hour() * 60 + QTime::currentTime().minute();
    settings.setValue("DayStart", QTime(0, 0).addSecs(((minute + 1439) % 1440) * 60).toString("HH:mm"));
    settings.setValue("NightStart", QTime(0, 0).addSecs(((minute + 1) % 1440) * 60).toString("HH:mm"));
    settings.sync();
    CHECK(theme.update() && theme.dayTheme());

    QQmlEngine engine;
    QQmlComponent mocks(&engine);
    mocks.setData(R"(
import QtQuick 2.0
QtObject {
    property QtObject renderer: QtObject {
        property bool ready: true
        property var lastParameters: ({})
        function invoke(action, parameters) { lastParameters = parameters; return 1 }
        signal requestFinished(var requestId, var result, string errorName, string errorMessage)
        signal errorOccurred(string message)
    }
    property QtObject browser: QtObject {
        property bool ready: true
        property bool busy: false
        property bool canGoBack: false
        property string error: ""
        property string name: "Messages"
        property var page: ({id: "root", title: "Messages", searchEnabled: true, actions: []})
        property var items: [
            {id: "one", title: "10010", subtitle: "First line\nSecond line\r\nThird line", enabled: true, kind: "folder"},
            {id: "two", title: "1001298", subtitle: "Long verification message with several embedded lines\n1. Answer one\n2. Answer two\n3. Answer three", enabled: true, kind: "folder"},
            {id: "three", title: "106863955301", subtitle: "Verification code 747435", enabled: true, kind: "folder"}
        ]
        function select(id) {}
        function back() {}
        function refresh() {}
        function more() {}
        function search(text) {}
        function action(id) {}
    }
}
)", QUrl());
    std::unique_ptr<QObject> fixture(mocks.create());
    CHECK(fixture);
    QObject *renderer = fixture->property("renderer").value<QObject *>();
    QObject *browser = fixture->property("browser").value<QObject *>();
    engine.rootContext()->setContextProperty("renderer", renderer);
    engine.rootContext()->setContextProperty("browser", browser);
    engine.rootContext()->setContextProperty("communicationState", QVariantMap{{"calls", QVariantList()}, {"smsAvailable", true}});
    engine.rootContext()->setContextProperty("phoneApp", true);
    engine.rootContext()->setContextProperty("dayTheme", false);
    QFile source(QString::fromLocal8Bit(argv[1]));
    CHECK(source.open(QIODevice::ReadOnly));
    QByteArray sourceData = source.readAll();
    // Keep the native window hidden while testing its scene with render control.
    sourceData.replace("visible: true", "visible: false");
    QQmlComponent component(&engine);
    component.setData(sourceData, QUrl::fromLocalFile(source.fileName()));
    std::unique_ptr<QObject> object(component.create());
    if (!object) for (const auto &error : component.errors()) fprintf(stderr, "%s\n", qPrintable(error.toString()));
    CHECK(object);
    auto window = qobject_cast<QQuickWindow *>(object.get());
    CHECK(window);
    window->setVisible(false);
    QQuickRenderControl layout;
    QQuickWindow surface(&layout);
    QQuickItem *content = window->contentItem()->childItems().value(0);
    CHECK(content);
    window->create();
    surface.create();
    content->setParentItem(surface.contentItem());
    if (argc > 2) layout.initialize(nullptr);
    const QVariantList summaries = browser->property("items").toList();
    for (const QSize size : {QSize(1780, 1080), QSize(1780, 720), QSize(1140, 720), QSize(660, 480), QSize(580, 1280)}) {
        window->resize(size);
        surface.resize(size);
        surface.contentItem()->setSize(size);
        // Hidden platform windows defer their geometry notifications. Deliver
        // the resize notifications before polishing the offscreen scene.
        QMetaObject::invokeMethod(window, "widthChanged", Q_ARG(int, size.width()));
        QMetaObject::invokeMethod(window, "heightChanged", Q_ARG(int, size.height()));
        for (bool day : {false, true}) {
            engine.rootContext()->setContextProperty("dayTheme", day);
            engine.rootContext()->setContextProperty("phoneApp", true);
            object->setProperty("composing", true);
            settle(layout);
            QObject *palette = object->property("colors").value<QObject *>();
            CHECK(palette && palette->property("day").toBool() == day);
            CHECK(window->color() == palette->property("background").value<QColor>());
            auto composer = itemsNamed(content, "communicationComposer").value(0);
            auto form = itemsNamed(content, "communicationForm").value(0);
            auto key = itemsNamed(content, "dialKey_0").value(0);
            CHECK(composer && form && key && key->height() > 30);
            CHECK(qAbs(form->x() * 2 + form->width() - composer->width()) < 1);
            CHECK(qAbs(form->y() * 2 + form->height() - composer->height()) < 1);
            CHECK(form->height() <= composer->height() + 1);
            auto recipient = itemsNamed(content, "communicationRecipient").value(0);
            CHECK(recipient);
            recipient->setProperty("text", QString());
            const QPointF point = key->mapToScene(QPointF(key->width() / 2, key->height() / 2));
            QTest::mouseClick(&surface, Qt::LeftButton, Qt::NoModifier, point.toPoint());
            CHECK(recipient->property("text").toString() == "1");
            if (argc > 2 && size == QSize(1780, 1080)) {
                surface.setColor(window->color());
                CHECK(layout.grab().save(QString::fromLocal8Bit(argv[2]) + (day ? "/phone-day.png" : "/phone-night.png")));
            }
            const QVariantList calls{QVariantMap{{"id", "test-call"}, {"number", "12345"}, {"status", "incoming"}, {"incoming", true}}};
            engine.rootContext()->setContextProperty("communicationState", QVariantMap{{"calls", calls}, {"smsAvailable", true}});
            object->setProperty("notice", "Request submitted");
            settle(layout);
            CHECK(composer->height() > 0 && form->y() >= 0);
            CHECK(composer->y() + composer->height() < composer->parentItem()->height());
            engine.rootContext()->setContextProperty("communicationState", QVariantMap{{"calls", QVariantList()}, {"smsAvailable", true}});
            object->setProperty("notice", QString());
            engine.rootContext()->setContextProperty("phoneApp", false);
            object->setProperty("composing", false);
            settle(layout);
            auto rows = itemsNamed(content, "contentRow");
            CHECK(rows.size() >= 3);
            for (QQuickItem *row : rows) checkTextBounds(row);
            CHECK(browser->property("items").toList() == summaries);
            if (argc > 2 && size == QSize(1780, 1080)) {
                surface.setColor(window->color());
                CHECK(layout.grab().save(QString::fromLocal8Bit(argv[2]) + (day ? "/messages-day.png" : "/messages-night.png")));
            }
            object->setProperty("composing", true);
            settle(layout);
            CHECK(form->height() <= composer->height() + 1);
            object->setProperty("composing", false);
            browser->setProperty("page", QVariantMap{{"id", "thread:1"}, {"title", "10010"}, {"hasMore", false}});
            settle(layout);
            auto messages = itemsNamed(content, "messageRow");
            CHECK(messages.size() >= 3);
            for (QQuickItem *row : messages) checkTextBounds(row);
            browser->setProperty("page", QVariantMap{{"id", "root"}, {"title", "Messages"}, {"searchEnabled", true}, {"actions", QVariantList()}});
            printf("COMMUNICATION_UI_PASS width=%d height=%d day=%d dial-centered touch summaries multiline-detail\n", size.width(), size.height(), day);
        }
    }
    content->setParentItem(window->contentItem());
    return 0;
}

int main(int argc, char **argv)
{
    try {
        if (argc == 2 && QByteArray(argv[1]) == "--theme") {
            QCoreApplication app(argc, argv);
            SailplayThemeSettings theme;
            theme.update();
            QFile config(SailplayThemeSettings::configPath());
            CHECK(config.open(QIODevice::ReadOnly));
            QProcess dconf;
            dconf.start(QStringLiteral("dconf"), {QStringLiteral("read"), QStringLiteral("/desktop/jolla/theme/color_scheme")});
            CHECK(dconf.waitForFinished(1000) && dconf.exitCode() == 0);
            printf("THEME_CONFIG_PASS sha256=%s day=%d followAmbience=%d scheme=%s\n",
                QCryptographicHash::hash(config.readAll(), QCryptographicHash::Sha256).toHex().constData(),
                theme.dayTheme(), theme.followAmbience(), dconf.readAllStandardOutput().trimmed().constData());
            return 0;
        }
        return runProbe(argc, argv);
    } catch (const std::exception &error) {
        fprintf(stderr, "%s\n", error.what());
        return 1;
    }
}
