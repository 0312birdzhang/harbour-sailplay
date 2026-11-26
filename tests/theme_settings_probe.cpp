#define main sailplayApplicationMain
#include "../display-source/carui/main.cpp"
#undef main

#include <QCryptographicHash>
#include <QQuickItem>
#include <QQmlExpression>
#include <QQmlProperty>
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

static void verifyWeatherState(const QString &directory)
{
    const QString cache = directory + QStringLiteral("/.local/share/org.sailfishos/weather/");
    const QByteArray primary = R"({"currentLocation":{"locationId":1,"city":"苏州","country":"中国","weather":{"populated":true,"temperature":0,"weatherType":"d000"}},"savedLocations":[{"locationId":2,"city":"上海","country":"中国","weather":{"populated":true,"temperature":18,"weatherType":"d100"}},{"locationId":1,"city":"duplicate"},{"locationId":3,"city":"Missing temperature","weather":{"populated":true}}]})";
    writeFile(cache + "met_norway.json", primary);
    writeFile(cache + "other.json", R"({"currentLocation":{"locationId":1,"city":"Other provider","weather":{"populated":true,"temperature":10}},"savedLocations":[]})");
    writeFile(cache + "broken.json", "not JSON");
    CarUiController controller(nullptr, false);
    require(controller.weatherLocations().size() == 4, "cached weather locations or deduplication failed");
    require(controller.dashboardWeatherLocation().isEmpty() && controller.dashboardWeather().isEmpty(), "weather must start unset");
    const QByteArray original = QCryptographicHash::hash(primary, QCryptographicHash::Sha256);
    require(!controller.setDashboardWeather("met_norway:999"), "missing weather selection accepted");
    require(controller.setDashboardWeather("met_norway:1"), "current weather selection failed");
    require(controller.dashboardWeather().value("temperature").toDouble() == 0
        && controller.dashboardWeather().value("populated").toBool(), "zero temperature became a placeholder");
    require(controller.setDashboardWeather("other:1") && controller.dashboardWeather().value("city") == "Other provider",
        "location IDs collided between providers");
    CarUiController restored(nullptr, false);
    require(restored.dashboardWeatherLocation() == "other:1", "weather selection did not persist");
    require(controller.setDashboardWeather("met_norway:3") && !controller.dashboardWeather().value("populated").toBool(),
        "missing temperature became fabricated conditions");
    require(controller.setDashboardWeather("met_norway:2"), "saved weather selection failed");
    writeFile(cache + "met_norway.json", "{}");
    QTest::qWait(1200);
    require(controller.dashboardWeather().isEmpty() && controller.dashboardWeatherLocation() == "met_norway:2",
        "removed weather location fell back to another city");
    require(controller.setDashboardWeather("") && controller.dashboardWeather().isEmpty(), "weather clear failed");
    writeFile(cache + "met_norway.json", primary);
    QFile file(cache + "met_norway.json");
    require(file.open(QIODevice::ReadOnly) && QCryptographicHash::hash(file.readAll(), QCryptographicHash::Sha256) == original,
        "weather selection changed the Weather cache");
    std::puts("DASHBOARD_WEATHER_STATE_PASS unset current saved provider-identity zero-temperature persistence missing clear cache-preserved");
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
    QQuickItem *weather = page->findChild<QQuickItem *>(QStringLiteral("dashboardWeatherButton"));
    std::fprintf(stderr, "WEATHER_SETTINGS_ENTRY exists=%d value=%s selection=%s\n", weather != nullptr,
        weather ? qPrintable(weather->property("value").toString()) : "", qPrintable(controller.dashboardWeatherLocation()));
    require(weather && weather->property("value").toString() == QString::fromUtf8("未设置"), "weather settings entry missing");
    QQmlExpression click(QQmlEngine::contextForObject(weather), weather, QStringLiteral("clicked(null)"));
    click.evaluate();
    require(!click.hasError(), "weather settings click failed");
    QTest::qWait(100);
    require(QMetaObject::invokeMethod(stack, "completeAnimation", Qt::DirectConnection), "weather page transition failed");
    QObject *weatherPage = stack->property("currentPage").value<QObject *>();
    require(weatherPage && weatherPage != page, "weather chooser did not open");
    require(QMetaObject::invokeMethod(weatherPage, "selectLocation", Q_ARG(QVariant, QVariant("met_norway:1"))),
        "weather chooser selection failed");
    QTest::qWait(100);
    require(QMetaObject::invokeMethod(stack, "completeAnimation", Qt::DirectConnection), "weather chooser did not close");
    require(controller.dashboardWeatherLocation() == "met_norway:1"
        && weather->property("value").toString() == QString::fromUtf8("苏州"), "weather selection did not update settings");
    require(controller.setDashboardWeather(""), "weather clear failed");
    std::puts("DASHBOARD_WEATHER_SETTINGS_UI_PASS entry chooser selection live-binding clear");
    QCoreApplication::removeTranslator(&translator);
}

static QQuickItem *findItem(QQuickItem *root, const QString &name)
{
    if (root->objectName() == name) return root;
    for (auto *child : root->childItems()) if (auto *found = findItem(child, name)) return found;
    return nullptr;
}

static void verifyDashboardUi()
{
    const QString directory = QString::fromLocal8Bit(qgetenv("SAILPLAY_THEME_UI_DIR"));
    std::unique_ptr<QQuickView> view(SailfishApp::createView());
    QQmlEngine *engine = view->engine();
    QQmlComponent fixture(engine, QUrl::fromLocalFile(QString::fromLocal8Bit(qgetenv("SAILPLAY_DASHBOARD_FIXTURE"))));
    std::unique_ptr<QObject> controller(fixture.create());
    require(controller.get(), "dashboard controller fixture failed");
    engine->rootContext()->setContextProperty("carController", controller.get());
    QFile file(directory + "/main.qml");
    require(file.open(QIODevice::ReadOnly), "dashboard source missing");
    QByteArray source = file.readAll();
    source.replace("visible: true; width:", "visible: false; width:");
    QQmlComponent component(engine);
    component.setData(source, QUrl::fromLocalFile(directory + "/main.qml"));
    std::unique_ptr<QObject> object(component.create());
    for (const QQmlError &error : component.errors()) std::fprintf(stderr, "%s\n", qPrintable(error.toString()));
    require(object.get(), "dashboard QML failed to load");
    auto *window = qobject_cast<QQuickWindow *>(object.get());
    require(window, "dashboard window missing");
    auto *dashboard = findItem(window->contentItem(), "dashboard");
    auto *info = findItem(window->contentItem(), "dashboardInfoCard");
    auto *music = findItem(window->contentItem(), "musicCard");
    auto *map = findItem(window->contentItem(), "dashboardMapCard");
    auto *summary = findItem(window->contentItem(), "dashboardNavigationSummary");
    auto *placeholder = findItem(window->contentItem(), "dashboardWeatherPlaceholder");
    auto *controls = findItem(window->contentItem(), "musicControls");
    require(dashboard && info && music && map && summary && placeholder && controls,
        "dashboard slots missing");
    const auto bounds = [&](QQuickItem *item) {
        return item->mapRectToItem(dashboard, QRectF(0, 0, item->width(), item->height()));
    };
    const auto verifyLayout = [&]() {
        const double gap = dashboard->property("verticalGap").toDouble();
        const double available = dashboard->height() - 3 * gap;
        require(std::abs(info->height() / available - 0.27) < 0.0001
            && std::abs(music->height() / available - 0.73) < 0.0001, "dashboard height allocation incorrect");
        require(music->y() == info->y() + info->height() + gap, "dashboard card gap changed");
        require(!bounds(info).intersects(bounds(music)) && !bounds(map).intersects(bounds(music)), "dashboard cards overlap");
        require(bounds(music).bottom() <= dashboard->height(), "music card exceeds dashboard");
    };
    QObject *navigation = controller->property("navigation").value<QObject *>();
    require(navigation, "navigation fixture missing");
    for (const QSize &size : {QSize(1920, 720), QSize(1280, 720), QSize(720, 1280)}) {
        window->resize(size);
        QTest::qWait(30);
        verifyLayout();
        auto *lyrics = findItem(window->contentItem(), "musicLyrics");
        require(lyrics && QQmlProperty(lyrics, "player").write(QVariant::fromValue<QObject *>(nullptr))
            && QQmlProperty(lyrics, "trackKey").write(QStringLiteral("dashboard-lyrics-test")),
            "lyrics fixture bindings could not be isolated");
        QVariantList lines;
        for (int index = 0; index < 10; ++index)
            lines.append(QVariant(QVariantList{index * 4, QString::fromUtf8("歌词第%1句").arg(index + 1)}));
        lyrics->setProperty("lines", lines);
        require(QQmlProperty(lyrics, "positionSeconds").write(12.0), "lyrics test position could not be set");
        QTest::qWait(30);
        require(controls->y() <= 24 && lyrics->height() > 24, "dashboard did not allocate space to lyrics");
        require(bounds(music).contains(bounds(lyrics)), "lyrics panel exceeds music card");
        require(!bounds(controls).intersects(bounds(lyrics)), "lyrics overlap playback controls");
        int completeLines = 0;
        for (int index = 0; index < 4; ++index) {
            auto *line = findItem(window->contentItem(), QStringLiteral("compactLyricLine_%1").arg(index));
            if (line && line->height() > 0 && bounds(lyrics).adjusted(-0.1, -0.1, 0.1, 0.1).contains(bounds(line)))
                ++completeLines;
        }
        std::printf("DASHBOARD_LYRICS_GEOMETRY %dx%d height=%.1f count=%d current=%d\n",
            size.width(), size.height(), lyrics->height(), completeLines,
            lyrics->property("currentIndex").toInt());
        require(completeLines >= 3, "dashboard lyrics display fewer than three complete lines");
        std::printf("DASHBOARD_LYRICS_PASS %dx%d height=%.1f completeLines=%d\n",
            size.width(), size.height(), lyrics->height(), completeLines);
        const double coverWithLyrics = controls->property("coverSize").toDouble();
        controller->setProperty("showMusicLyrics", false);
        QTest::qWait(30);
        require(!findItem(window->contentItem(), "musicLyrics") && controls->property("centered").toBool(),
            "lyrics toggle did not switch to centered playback");
        require(std::abs(bounds(controls).center().x() - bounds(music).center().x()) < 0.5
            && bounds(music).contains(bounds(controls)), "centered player exceeds or is misaligned with its card");
        if (size == QSize(1920, 720))
            require(controls->property("coverSize").toDouble() > coverWithLyrics, "hidden lyrics did not enlarge the cover");
        controller->setProperty("showMusicLyrics", true);
        const QRectF reserve = bounds(info);
        require(placeholder->isVisible() && !summary->isVisible(), "unset weather did not retain placeholder");
        controller->setProperty("dashboardWeatherLocation", "met_norway:1");
        controller->setProperty("dashboardWeather", QVariantMap{{"city", QString::fromUtf8("苏州")},
            {"populated", true}, {"temperature", 0}, {"weatherType", "d000"}});
        require(!placeholder->isVisible() && bounds(info) == reserve, "weather moved reserved space");
        for (const QString &name : {QStringLiteral("dashboardWeatherTemperature"), QStringLiteral("dashboardWeatherCity")}) {
            auto *label = findItem(window->contentItem(), name);
            require(label && bounds(info).contains(bounds(label)), "weather label exceeds info card");
        }
        controller->setProperty("dashboardMapApp", "test-map");
        controller->setProperty("dashboardNavigationTemplate", true);
        const QVariantMap activeGuidance{{"state", "active"}, {"maneuver", "roundabout-exit"},
            {"drivingSide", "left"}, {"exitNumber", 3}, {"nextDistanceMeters", 370},
            {"nextRoad", QString::fromUtf8("测试道路名称很长时仍保持在卡片内")},
            {"remainingSeconds", 61}, {"remainingDistanceMeters", 2400}};
        navigation->setProperty("navigating", true);
        navigation->setProperty("guidance", activeGuidance);
        require(summary->isVisible() && bounds(info) == reserve, "navigation did not replace weather in its slot");
        for (const QString &name : {QStringLiteral("dashboardManeuver"), QStringLiteral("dashboardNextDistance"),
                                    QStringLiteral("dashboardNextRoad"), QStringLiteral("dashboardRemainingRoute")}) {
            auto *label = findItem(window->contentItem(), name);
            require(label && bounds(info).contains(bounds(label)), "guidance label exceeds info card");
        }
        require(findItem(window->contentItem(), "dashboardManeuver")->property("text").toString() == QString::fromUtf8("⟲ 3"),
            "dashboard lost left-driving roundabout mapping");
        require(findItem(window->contentItem(), "dashboardNextDistance")->property("text").toString() == "370 m",
            "dashboard maneuver distance incorrect");
        auto *weatherCity = findItem(window->contentItem(), "dashboardWeatherCity");
        auto *status = findItem(summary, "dashboardNavigationStatus");
        auto *distance = findItem(summary, "dashboardNextDistance");
        auto *lastRoute = findItem(summary, "dashboardLastRoute");
        require(weatherCity && status && distance && lastRoute && !weatherCity->isVisible() && !status->isVisible(),
            "navigation left weather or a status visible");
        navigation->setProperty("lastRouteOverview", QVariantMap{{"destination", QString::fromUtf8("测试目的地")},
            {"remainingSeconds", 61}, {"remainingDistanceMeters", 2400}});
        navigation->setProperty("guidance", QVariantMap{{"state", "unavailable"}});
        controller->setProperty("dashboardWeather", QVariantMap{{"city", QString::fromUtf8("上海")},
            {"populated", true}, {"temperature", 12}, {"weatherType", "d000"}});
        require(summary->isVisible() && status->isVisible() && lastRoute->isVisible() && !distance->isVisible()
            && !weatherCity->isVisible(),
            "temporary loss of guidance let a weather update reclaim the card");
        navigation->setProperty("ready", false);
        navigation->setProperty("guidance", QVariantMap());
        require(summary->isVisible() && status->isVisible() && !weatherCity->isVisible(),
            "provider reconnect let weather reclaim the card");
        navigation->setProperty("ready", true);
        navigation->setProperty("guidance", activeGuidance);
        require(summary->isVisible() && !status->isVisible() && distance->isVisible() && !weatherCity->isVisible(),
            "fresh instructions did not restore the navigation summary");
        for (const QString &state : {QStringLiteral("stopped"), QStringLiteral("arrived"), QStringLiteral("idle")}) {
            navigation->setProperty("navigating", true);
            navigation->setProperty("guidance", activeGuidance);
            navigation->setProperty("guidance", QVariantMap{{"state", state}});
            navigation->setProperty("navigating", false);
            require(!summary->isVisible() && weatherCity->isVisible()
                && weatherCity->property("text").toString() == QString::fromUtf8("上海"),
                "ending navigation did not restore the latest weather");
        }
        controller->setProperty("dashboardMapApp", "");
        controller->setProperty("dashboardNavigationTemplate", false);
        controller->setProperty("dashboardWeatherLocation", "");
        controller->setProperty("dashboardWeather", QVariantMap());
        require(placeholder->isVisible() && bounds(info) == reserve, "missing weather/map collapsed the slot");
        std::printf("DASHBOARD_LAYOUT_PASS %dx%d info=27%% music=73%% placeholder weather navigation stop\n", size.width(), size.height());
    }
    // Release the Window's QML instances before tearing down the engine.
    object.reset();
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
        qputenv("XDG_DATA_HOME", (directory.path() + "/.local/share").toUtf8());
        qputenv("SAILPLAY_DIAGNOSTICS_CONFIG", (directory.path() + "/diagnostics.ini").toUtf8());
        QGuiApplication app(argc, argv);
        qmlRegisterType<SailplayMapCanvas>("Sailplay", 1, 0, "MapCanvas");
        verifyWeatherState(directory.path());
        verifyThemeState(directory.path());
        verifySettingsUi();
        if (!qgetenv("SAILPLAY_DASHBOARD_FIXTURE").isEmpty()) verifyDashboardUi();
        return 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "THEME_SETTINGS_FAILED %s\n", error.what());
        return 1;
    }
}
