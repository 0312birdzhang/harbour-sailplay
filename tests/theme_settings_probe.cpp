#define main sailplayApplicationMain
#include "../display-source/carui/main.cpp"
#undef main

#include <QCryptographicHash>
#include <QQuickItem>
#include <QTemporaryDir>
#include <QtTest/QTest>
#include <memory>
#include <stdexcept>

static void require(bool condition, const char *message)
{
    if (!condition) throw std::runtime_error(message);
}

static void writeFile(const QString &path, const QByteArray &data)
{
    // Qt 5.6 caches same-size external INI edits by the file timestamp.
    if (QFileInfo(path).size() == data.size()) QTest::qWait(1100);
    QDir().mkpath(QFileInfo(path).absolutePath());
    QFile file(path);
    require(file.open(QIODevice::WriteOnly), "test file could not be opened");
    require(file.write(data) == data.size(), "test file write failed");
}

static void verifyThemeState(const QString &directory)
{
    const QString config = SailplayThemeSettings::configPath();
    const QString vehicle = directory + QStringLiteral("/vehicle.ini");
    const QString bin = directory + QStringLiteral("/bin");
    writeFile(bin + QStringLiteral("/dconf"), "#!/bin/sh\nprintf '1\\n'\n");
    require(QFile::setPermissions(bin + QStringLiteral("/dconf"), QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner),
            "test dconf permission failed");
    qputenv("PATH", bin.toUtf8() + ':' + qgetenv("PATH"));
    SailplayThemeSettings theme(vehicle);
    require(theme.mode() == SailplayThemeSettings::Ambience, "default mode changed");
    writeFile(config, "[General]\nFollowAmbience=false\nDayStart=08:20\nNightStart=20:30\n");
    require(theme.mode() == SailplayThemeSettings::Custom && theme.dayStart() == "08:20" && theme.nightStart() == "20:30",
            "legacy schedule migration failed");
    writeFile(config, "[General]\nFollowAmbience=true\n");
    require(theme.mode() == SailplayThemeSettings::Ambience, "legacy ambience migration failed");
    writeFile(config, "[General]\nMode=headlights\n");
    require(theme.update() && theme.dayTheme(), "missing vehicle state must follow ambience");
    require(!theme.update(), "unchanged theme emitted a change");
    QFile owner(directory + QStringLiteral("/session.lock"));
    require(owner.open(QIODevice::ReadWrite), "session lock unavailable");
    require(flock(owner.handle(), LOCK_EX | LOCK_NB) == 0, "session lock acquisition failed");
    require(owner.write("test-session") == 12 && owner.flush(), "session identity write failed");
    const QByteArray identity = "[Vehicle]\nSession=test-session\nNightMode=";
    writeFile(vehicle, identity + "true\n");
    require(theme.update() && !theme.dayTheme(), "headlights on must use dark theme");
    writeFile(vehicle, identity + "false\n");
    require(theme.update() && theme.dayTheme(), "headlights off must use light theme");
    require(flock(owner.handle(), LOCK_UN) == 0, "session lock release failed");
    writeFile(vehicle, identity + "true\n");
    theme.update();
    require(theme.dayTheme(), "dead vehicle session was accepted");
    require(flock(owner.handle(), LOCK_EX | LOCK_NB) == 0, "session lock reacquisition failed");
    writeFile(vehicle, "[Vehicle]\nSession=stale-session\nNightMode=true\n");
    theme.update();
    require(theme.dayTheme(), "stale session identity was accepted");
    writeFile(vehicle, identity + "unknown\n");
    theme.update();
    require(theme.dayTheme(), "unknown vehicle state must follow ambience");
    writeFile(vehicle, identity + "true\n");
    writeFile(config, "[General]\nMode=ambience\n");
    require(theme.update() && theme.dayTheme(), "ambience mode used the vehicle signal");
    const int minute = QTime::currentTime().hour() * 60 + QTime::currentTime().minute();
    const QTime day = QTime(0, 0).addSecs(((minute + 1430) % 1440) * 60);
    const QTime night = QTime(0, 0).addSecs(((minute + 10) % 1440) * 60);
    writeFile(config, "[General]\nMode=custom\nDayStart=" + day.toString("HH:mm").toUtf8()
              + "\nNightStart=" + night.toString("HH:mm").toUtf8() + '\n');
    require(theme.update() && theme.dayTheme(), "custom day schedule failed");
    writeFile(config, "[General]\nMode=custom\nDayStart=" + night.toString("HH:mm").toUtf8()
              + "\nNightStart=" + day.toString("HH:mm").toUtf8() + '\n');
    require(theme.update() && !theme.dayTheme(), "custom night schedule failed");
    writeFile(config, "[General]\nMode=custom\nDayStart=invalid\nNightStart=25:70\n");
    require(theme.dayStart() == "07:00" && theme.nightStart() == "19:00", "invalid saved time fallback failed");
    writeFile(config, "[General]\nMode=unknown\nFollowAmbience=false\n");
    require(theme.mode() == SailplayThemeSettings::Custom, "unknown mode legacy fallback failed");
    std::puts("THEME_STATE_PASS legacy default headlights ambience custom invalid stale-session");
}

static void verifySettingsUi()
{
    const QString uiDirectory = qEnvironmentVariableIsSet("SAILPLAY_THEME_UI_DIR")
        ? QString::fromLocal8Bit(qgetenv("SAILPLAY_THEME_UI_DIR")) : QStringLiteral("/opt/sailplay/carui");
    QTranslator translator;
    require(translator.load(uiDirectory + QStringLiteral("/translations/sailplay_zh_CN.qm")), "Chinese catalog missing");
    QCoreApplication::installTranslator(&translator);
    const QString config = SailplayThemeSettings::configPath();
    writeFile(config, "[General]\nFollowAmbience=true\nDayStart=08:20\nNightStart=20:30\n");
    CarUiController controller(nullptr, false);
    std::unique_ptr<QQuickView> view(SailfishApp::createView());
    view->setResizeMode(QQuickView::SizeRootObjectToView);
    view->resize(720, 1280);
    view->rootContext()->setContextProperty("carController", &controller);
    view->setSource(QUrl::fromLocalFile(uiDirectory + QStringLiteral("/mobile-settings.qml")));
    require(view->status() != QQuickView::Error, "settings QML failed to load");
    QTest::qWait(500);
    QObject *stack = view->rootObject()->property("pageStack").value<QObject *>();
    require(stack && QMetaObject::invokeMethod(stack, "completeAnimation", Qt::DirectConnection), "settings page unavailable");
    QObject *page = stack->property("currentPage").value<QObject *>();
    require(page, "settings initial page missing");
    QQuickItem *combo = page->findChild<QQuickItem *>(QStringLiteral("themeModeComboBox"));
    QQuickItem *day = page->findChild<QQuickItem *>(QStringLiteral("dayThemeTimeButton"));
    QQuickItem *night = page->findChild<QQuickItem *>(QStringLiteral("nightThemeTimeButton"));
    require(combo && day && night, "theme controls missing");
    require(combo->property("currentIndex").toInt() == 1, "legacy mode did not select ambience");
    QObject *menu = combo->property("menu").value<QObject *>();
    require(menu, "theme combo menu missing");
    QList<QObject *> options;
    for (QObject *object : menu->children()) {
        if (object->property("text").isValid()) options.append(object);
    }
    const QStringList labels{QStringLiteral("大灯联动"), QStringLiteral("跟随手机氛围"), QStringLiteral("自定义")};
    require(options.size() == labels.size(), "theme combo must have exactly three options");
    for (int index : {0, 1, 2, 0, 2, 1}) {
        require(options.at(index)->property("text").toString() == labels.at(index), "theme option text/order incorrect");
        require(QMetaObject::invokeMethod(options.at(index), "clicked", Qt::DirectConnection), "theme menu click failed");
        QTest::qWait(40);
        std::fprintf(stderr, "THEME_SELECTION requested=%d persisted=%d combo=%d dayVisible=%d nightVisible=%d\n",
            index, controller.themeMode(), combo->property("currentIndex").toInt(), day->isVisible(), night->isVisible());
        require(controller.themeMode() == index && combo->property("currentIndex").toInt() == index, "theme selection failed to persist/bind");
        require(day->isVisible() == (index == 2) && night->isVisible() == (index == 2), "custom time controls visibility incorrect");
        require(controller.dayStart() == "08:20" && controller.nightStart() == "20:30", "mode switch changed custom times");
        std::printf("THEME_SETTINGS_UI_PASS mode=%d customTimes=%d label=%s\n", index, day->isVisible(), qPrintable(labels.at(index)));
    }
    require(!controller.setThemeMode(-1) && !controller.setThemeMode(3), "invalid theme mode accepted");
    require(controller.setThemeTime(true, "08:45"), "custom time save failed");
    require(!controller.setThemeTime(false, "08:45"), "equal theme times accepted");
    CarUiController restored(nullptr, false);
    require(restored.themeMode() == 1 && restored.dayStart() == "08:45" && restored.nightStart() == "20:30", "saved settings did not survive controller recreation");
    QCoreApplication::removeTranslator(&translator);
}

int main(int argc, char **argv)
{
    try {
        if (argc == 2 && QByteArray(argv[1]) == "--watch") {
            QCoreApplication app(argc, argv);
            SailplayThemeSettings theme;
            for (int step = 0; step < 60; ++step) {
                theme.update();
                QFile config(SailplayThemeSettings::configPath());
                require(config.open(QIODevice::ReadOnly), "sandbox theme config unavailable");
                std::printf("THEME_WATCH step=%d mode=%d day=%d sha256=%s\n", step, theme.mode(), theme.dayTheme(),
                    QCryptographicHash::hash(config.readAll(), QCryptographicHash::Sha256).toHex().constData());
                QSettings vehicle(SailplayThemeSettings::vehiclePath(), QSettings::IniFormat);
                QFile process(QStringLiteral("/proc/%1/stat").arg(vehicle.value("Vehicle/PID").toString()));
                std::printf("THEME_VEHICLE_READ night=%s procOpen=%d\n", qPrintable(vehicle.value("Vehicle/NightMode").toString()),
                    process.open(QIODevice::ReadOnly));
                std::fflush(stdout);
                QTest::qWait(300);
            }
            return 0;
        }
        QTemporaryDir directory;
        require(directory.isValid(), "isolated test directory unavailable");
        qputenv("HOME", directory.path().toUtf8());
        qputenv("XDG_CONFIG_HOME", (directory.path() + "/.config").toUtf8());
        qputenv("SAILPLAY_DIAGNOSTICS_CONFIG", (directory.path() + "/diagnostics.ini").toUtf8());
        QGuiApplication app(argc, argv);
        verifyThemeState(directory.path());
        verifySettingsUi();
        return 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "THEME_SETTINGS_FAILED %s\n", error.what());
        return 1;
    }
}
