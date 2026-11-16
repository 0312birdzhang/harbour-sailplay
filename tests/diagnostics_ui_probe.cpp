#define main sailplayApplicationMain
#include "../display-source/carui/main.cpp"
#undef main

#include <QQuickItem>
#include <QQmlExpression>
#include <QTemporaryDir>
#include <QtTest/QTest>
#include <memory>
#include <stdexcept>

static bool logicOnly = false;

static void require(bool condition, const char *message)
{
    if (!condition) throw std::runtime_error(message);
}

static void verifyDiagnosticTranslations()
{
    const char *sources[] = {
        "Collect diagnostic logs",
        "Save detailed connection logs privately and rotate them automatically. The setting takes effect during the current session.",
        "Could not save diagnostic logging setting"
    };
    struct Catalog {
        const char *language;
        QStringList expected;
    };
    const Catalog catalogs[] = {
        {"zh_CN", {QStringLiteral("收集诊断日志"),
                   QStringLiteral("详细连接日志保存在私有目录中，并自动轮转。设置立即生效。"),
                   QStringLiteral("无法保存诊断日志设置")}},
        {"zh_TW", {QStringLiteral("收集診斷日誌"),
                   QStringLiteral("詳細連線日誌儲存於私有目錄，並自動輪替。設定立即生效。"),
                   QStringLiteral("無法儲存診斷日誌設定")}},
        {"de", {QStringLiteral("Diagnoseprotokolle aufzeichnen"),
                QStringLiteral("Detaillierte Verbindungsprotokolle privat speichern und automatisch rotieren. Die Einstellung gilt für die laufende Sitzung."),
                QStringLiteral("Die Einstellung für Diagnoseprotokolle konnte nicht gespeichert werden")}},
        {"fr", {QStringLiteral("Collecter les journaux de diagnostic"),
                QStringLiteral("Enregistrer les journaux de connexion détaillés de façon privée avec rotation automatique. Le réglage prend effet pendant la session en cours."),
                QStringLiteral("Impossible d’enregistrer le réglage des journaux de diagnostic")}},
        {"ru", {QStringLiteral("Собирать диагностические журналы"),
                QStringLiteral("Сохранять подробные журналы подключений в приватном каталоге с автоматической ротацией. Настройка действует в текущем сеансе."),
                QStringLiteral("Не удалось сохранить настройку диагностических журналов")}}
    };
    for (const Catalog &catalog : catalogs) {
        QTranslator translator;
        require(translator.load(QStringLiteral("/opt/sailplay/carui/translations/sailplay_%1.qm")
                                .arg(QString::fromLatin1(catalog.language))), "installed translation catalog failed to load");
        for (int index = 0; index < 3; ++index) {
            const QString actual = translator.translate("Sailplay", sources[index]);
            require(actual == catalog.expected.at(index), "installed diagnostic translation is incorrect");
        }
    }
    std::puts("DIAGNOSTICS_COMPILED_TRANSLATIONS_PASS languages=5 messages=15");
    std::fflush(stdout);
}

static QQuickItem *openAbout(QQuickView *view, CarUiController *controller)
{
    view->setResizeMode(QQuickView::SizeRootObjectToView);
    view->resize(720, 1280);
    QObject::connect(view, &QQuickWindow::sceneGraphError, view,
                     [](QQuickWindow::SceneGraphError error, const QString &message) {
        std::fprintf(stderr, "UI_PROBE_SCENE_GRAPH_ERROR code=%d message=%s\n", error, qPrintable(message));
    });
    view->rootContext()->setContextProperty("carController", controller);
    view->setSource(QUrl::fromLocalFile(QStringLiteral("/opt/sailplay/carui/mobile-settings.qml")));
    require(view->status() != QQuickView::Error, "mobile settings QML failed to load");
    if (!logicOnly) {
        view->show();
        view->requestActivate();
    }
    QTest::qWait(600);
    QObject *stack = view->rootObject()->property("pageStack").value<QObject *>();
    require(stack, "mobile settings page stack is missing");
    require(QMetaObject::invokeMethod(stack, "completeAnimation", Qt::DirectConnection), "initial page animation failed");
    QObject *menu = view->rootObject()->findChild<QObject *>(QStringLiteral("aboutMenuItem"));
    require(menu, "normal About menu entry is missing");
    require(QMetaObject::invokeMethod(menu, "clicked", Qt::DirectConnection), "About menu click failed");
    QTest::qWait(600);
    require(QMetaObject::invokeMethod(stack, "completeAnimation", Qt::DirectConnection), "About page animation failed");
    QQuickItem *page = qobject_cast<QQuickItem *>(stack->property("currentPage").value<QObject *>());
    std::fprintf(stderr, "UI_ABOUT_PAGE depth=%d name=%s visible=%d window=%dx%d exposed=%d\n",
                 stack->property("depth").toInt(), page ? qPrintable(page->objectName()) : "missing",
                 page && page->isVisible(), view->width(), view->height(), view->isExposed());
    require(page && page->objectName() == QStringLiteral("sailplayAboutPage") && (logicOnly || page->isVisible()),
            "About page failed to open from normal menu");
    return page;
}

static void tap(QQuickView *view, QQuickItem *item)
{
    require(item && (logicOnly || item->isVisible()), "tap target is missing or hidden");
    if (logicOnly) {
        QQmlExpression click(QQmlEngine::contextForObject(item), item, QStringLiteral("clicked(null)"));
        click.evaluate();
        require(!click.hasError(), "QML click handler failed");
    } else {
        const QPoint position = item->mapToScene(QPointF(item->width() / 2, item->height() / 2)).toPoint();
        QTest::mouseClick(view, Qt::LeftButton, Qt::NoModifier, position);
    }
    QTest::qWait(50);
}

static QQuickItem *unlock(QQuickView *view, QQuickItem *page)
{
    QQuickItem *toggle = page->findChild<QQuickItem *>(QStringLiteral("sailplayLoggingSwitch"));
    require(toggle && !page->property("diagnosticsUnlocked").toBool(), "logging switch must start hidden when collection is disabled");
    require(logicOnly || !toggle->isVisible(), "logging switch must start invisible");
    require(toggle->property("text").toString() == QStringLiteral("收集诊断日志"), "logging switch Chinese text is incorrect");
    require(toggle->property("description").toString() == QStringLiteral("详细连接日志保存在私有目录中，并自动轮转。设置立即生效。"),
            "logging switch Chinese description is incorrect");
    std::fprintf(stderr, "UI_LOGGING_TEXT %s\n", qPrintable(toggle->property("text").toString()));
    QQuickItem *icon = page->findChild<QQuickItem *>(QStringLiteral("sailplayAboutIconTap"));
    QQuickItem *name = page->findChild<QQuickItem *>(QStringLiteral("sailplayAboutNameTap"));
    for (int click = 1; click <= 10; ++click) {
        tap(view, click % 2 ? icon : name);
        require(page->property("diagnosticTapCount").toInt() == click, "combined icon/name tap count is incorrect");
        require(page->property("diagnosticsUnlocked").toBool() == (click == 10), "logging switch unlocked at the wrong tap count");
        require(logicOnly || toggle->isVisible() == (click == 10), "logging switch revealed at the wrong tap count");
    }
    return toggle;
}

Q_DECL_EXPORT int main(int argc, char **argv)
{
    logicOnly = qgetenv("SAILPLAY_DIAGNOSTICS_UI_LOGIC_ONLY") == "1";
    QTemporaryDir settings;
    if (qgetenv("SAILPLAY_DIAGNOSTICS_CONFIG").isEmpty())
        qputenv("SAILPLAY_DIAGNOSTICS_CONFIG", (settings.path() + QStringLiteral("/diagnostics.ini")).toUtf8());
    installMobileDiagnostics();
    inheritSystemLocale();
    QGuiApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("harbour-sailplay"));
    std::unique_ptr<QQuickView> themeView(SailfishApp::createView());
    try {
        verifyDiagnosticTranslations();
        QTranslator uiTranslator;
        require(uiTranslator.load(QStringLiteral("/opt/sailplay/carui/translations/sailplay_zh_CN.qm")),
                "phone Chinese catalog failed to load");
        app.installTranslator(&uiTranslator);
        require(!QFile::exists(diagnosticsConfigPath()), "test requires an absent diagnostic setting");
        qInfo("DIAGNOSTICS_DEFAULT_OFF_PROBE");
        {
            CarUiController controller(nullptr, false);
            controller.reloadConfig();
            require(!controller.loggingEnabled(), "diagnostic collection must default off");
            std::unique_ptr<QQuickView> view(SailfishApp::createView());
            QQuickItem *page = openAbout(view.get(), &controller);
            QQuickItem *toggle = unlock(view.get(), page);
            require(!toggle->property("checked").toBool(), "logging switch must default unchecked");
            tap(view.get(), toggle);
            require(controller.loggingEnabled(), "UI click failed to enable persistent setting");
            qInfo("DIAGNOSTICS_ENABLED_UI_PROBE");
            QTest::qWait(3000);
        }
        {
            CarUiController controller(nullptr, false);
            controller.reloadConfig();
            require(controller.loggingEnabled(), "enabled setting did not survive controller recreation");
            std::unique_ptr<QQuickView> view(SailfishApp::createView());
            QQuickItem *page = openAbout(view.get(), &controller);
            QQuickItem *toggle = page->findChild<QQuickItem *>(QStringLiteral("sailplayLoggingSwitch"));
            require(toggle && page->property("diagnosticsUnlocked").toBool(), "enabled logging switch must show immediately");
            require(page->property("diagnosticTapCount").toInt() == 0, "enabled logging must not require diagnostic taps");
            require(logicOnly || toggle->isVisible(), "enabled logging switch is hidden");
            require(toggle->property("checked").toBool(), "restored switch is not checked");
            std::puts("DIAGNOSTICS_ENABLED_VISIBLE_WITHOUT_TAPS_PASS");
            tap(view.get(), toggle);
            require(!controller.loggingEnabled(), "UI click failed to disable collection");
            require(page->property("diagnosticsUnlocked").toBool(), "switch should stay available after disabling on the same page");
            std::puts("DIAGNOSTICS_DISABLED_VISIBLE_CURRENT_PAGE_PASS");
            qInfo("DIAGNOSTICS_DISABLED_UI_PROBE");
            QTest::qWait(3000);
        }
        {
            CarUiController controller(nullptr, false);
            controller.reloadConfig();
            require(!controller.loggingEnabled(), "disabled setting did not survive controller recreation");
            std::unique_ptr<QQuickView> view(SailfishApp::createView());
            QQuickItem *page = openAbout(view.get(), &controller);
            require(!page->property("diagnosticsUnlocked").toBool(), "disabled logging must hide the switch on a new About page");
            std::puts("DIAGNOSTICS_DISABLED_HIDDEN_NEW_PAGE_PASS");
        }
        require(!diagnosticLoggingEnabled(), "disabled setting did not persist");
        std::puts("DIAGNOSTICS_ABOUT_TEN_TAPS_AND_PERSISTENCE_PASS");
        return 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "DIAGNOSTICS_UI_PROBE_FAILED %s\n", error.what());
        return 1;
    }
}
