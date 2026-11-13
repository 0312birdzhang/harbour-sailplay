#include "sailfish/app_info.hpp"
#include "sailfish/app_settings.hpp"
#include "sailfish/bookmark_editor.hpp"
#include "sailfish/bookmarks_io.hpp"
#include "sailfish/bookmarks_model.hpp"
#include "sailfish/countries_model.hpp"
#include "sailfish/framework_access.hpp"
#include "sailfish/map_item.hpp"
#include "sailfish/map_surface.hpp"
#include "sailfish/maps_storage.hpp"
#include "sailfish/opening_hours_editor.hpp"
#include "sailfish/osm_account.hpp"
#include "sailfish/phone_presentation.hpp"
#include "sailfish/place_editor.hpp"
#include "sailfish/place_page.hpp"
#include "sailfish/routing.hpp"
#include "sailfish/sailplay_map_canvas.hpp"
#include "sailfish/sailplay_map_browser.hpp"
#include "sailfish/search_model.hpp"
#include "sailfish/url_handler.hpp"

#include "map/framework.hpp"
#include "map/gps_tracker.hpp"
#include "geometry/mercator.hpp"

#include "platform/platform.hpp"
#include "platform/distance.hpp"

#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QGuiApplication>
#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QPointer>
#include <QQuickWindow>
#include <QSet>
#include <QStandardPaths>
#include <QSurfaceFormat>
#include <QThread>

#include <algorithm>
#include <clocale>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>

#include <sailfishapp.h>

namespace
{
Framework * g_framework = nullptr;

void Check(bool condition, char const * message)
{
  if (!condition)
  {
    std::fprintf(stderr, "MAP_LIFECYCLE_CHECK_FAILED %s\n", message);
    std::exit(EXIT_FAILURE);
  }
}

void WaitFor(std::function<bool()> const & ready, int timeoutMs = 10000)
{
  QElapsedTimer timer;
  timer.start();
  while (!ready() && timer.elapsed() < timeoutMs)
  {
    QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
    QThread::msleep(10);
  }
  Check(ready(), "event deadline exceeded");
}

double RemainingMeters(QJsonObject const & navigation)
{
  platform::Distance const distance(navigation.value("remainingDistance").toDouble(),
      static_cast<platform::Distance::Units>(navigation.value("remainingDistanceUnit").toInt()));
  return distance.To(platform::Distance::Units::Meters).GetDistance();
}

void RegisterTypes()
{
  qmlRegisterUncreatableType<sailfish::MapItem>("app.organicmaps", 1, 0, "MapItem", "Use mapCore");
  qmlRegisterType<sailfish::MapSurface>("app.organicmaps", 1, 0, "MapSurface");
  qmlRegisterType<sailfish::CountriesModel>("app.organicmaps", 1, 0, "CountriesModel");
  qmlRegisterType<sailfish::SearchModel>("app.organicmaps", 1, 0, "SearchModel");
  qmlRegisterType<sailfish::BookmarkCategoriesModel>("app.organicmaps", 1, 0, "BookmarkCategoriesModel");
  qmlRegisterType<sailfish::BookmarksModel>("app.organicmaps", 1, 0, "BookmarksModel");
  qmlRegisterType<sailfish::BookmarkEditor>("app.organicmaps", 1, 0, "BookmarkEditor");
  qmlRegisterType<sailfish::PlaceEditor>("app.organicmaps", 1, 0, "PlaceEditor");
  qmlRegisterType<sailfish::PlaceCategories>("app.organicmaps", 1, 0, "PlaceCategories");
  qmlRegisterType<sailfish::OpeningHoursEditor>("app.organicmaps", 1, 0, "OpeningHoursEditor");
  qmlRegisterUncreatableType<sailfish::PlacePage>("app.organicmaps", 1, 0, "PlacePage", "Owned by MapItem");
  qmlRegisterUncreatableType<sailfish::Routing>("app.organicmaps", 1, 0, "Routing", "Owned by MapItem");
  qmlRegisterUncreatableType<sailfish::AppSettings>("app.organicmaps", 1, 0, "AppSettings", "Use appSettings");
  qmlRegisterUncreatableType<sailfish::BookmarksIO>("app.organicmaps", 1, 0, "BookmarksIO", "Use bookmarksIO");
}
}  // namespace

namespace sailfish
{
Framework & GetFramework()
{
  return *g_framework;
}
}  // namespace sailfish

__attribute__((visibility("default"))) int OrganicMapsMain(int argc, char * argv[])
{
  QGuiApplication::setAttribute(Qt::AA_ShareOpenGLContexts);
  QSurfaceFormat format;
  format.setRenderableType(QSurfaceFormat::OpenGLES);
  format.setVersion(3, 0);
  format.setDepthBufferSize(24);
  format.setStencilBufferSize(8);
  QSurfaceFormat::setDefaultFormat(format);
  std::unique_ptr<QGuiApplication> application(SailfishApp::application(argc, argv));
  application->setQuitOnLastWindowClosed(false);
  application->setOrganizationName("app.organicmaps");
  application->setApplicationName("organicmaps");
  std::setlocale(LC_NUMERIC, "C");
  Check(argc == 2, "pass the installed or candidate QML directory");
  Check(!qEnvironmentVariableIsEmpty("MWM_WRITABLE_DIR"), "use an isolated writable profile");
  auto const writable = QDir(QString::fromUtf8(qgetenv("MWM_WRITABLE_DIR"))).absolutePath();
  Check(writable.startsWith("/tmp/sailplay-map-device."), "writable profile must be this fixture's temporary directory");
  Check(QStandardPaths::writableLocation(QStandardPaths::ConfigLocation).startsWith("/tmp/sailplay-map-device."),
        "use this fixture's isolated configuration");
  QString const qmlRoot = QString::fromLocal8Bit(argv[1]);

  Framework framework;
  g_framework = &framework;
  framework.SetupMeasurementSystem();
  sailfish::BookmarksNotifier::LoadBookmarks(framework);
  RegisterTypes();
  sailfish::AppInfo appInfo;
  sailfish::AppSettings appSettings(framework);
  sailfish::OsmAccount osmAccount;
  sailfish::BookmarksIO bookmarksIO(framework);
  sailfish::MapsStorage mapsStorage(framework);
  sailfish::DownloadStatus downloads(framework.GetStorage());
  sailfish::UrlHandler urlHandler(framework, bookmarksIO);
  sailfish::MapItem mapCore;
  QQmlEngine::setObjectOwnership(&mapCore, QQmlEngine::CppOwnership);
  auto const setup = [&](QQmlContext * context)
  {
    context->setContextProperty("appInfo", &appInfo);
    context->setContextProperty("appSettings", &appSettings);
    context->setContextProperty("osmAccount", &osmAccount);
    context->setContextProperty("bookmarksIO", &bookmarksIO);
    context->setContextProperty("mapsStorage", &mapsStorage);
    context->setContextProperty("downloads", &downloads);
    context->setContextProperty("urlHandler", &urlHandler);
    context->setContextProperty("mapCore", &mapCore);
    context->setContextProperty("sailplayProjected", false);
  };
  sailfish::PhonePresentation presentation(QUrl::fromLocalFile(qmlRoot + "/organicmaps.qml"), setup);
  QQmlEngine backendEngine;
  setup(backendEngine.rootContext());
  QQmlComponent backendComponent(&backendEngine, QUrl::fromLocalFile(qmlRoot + "/Backend.qml"));
  std::unique_ptr<QObject> backendObject(backendComponent.create());
  Check(backendObject != nullptr, "windowless backend QML failed");
  Check(!framework.IsDrapeEngineCreated() && mapCore.window() == nullptr, "cold backend created a renderer");
  Check(!mapCore.trackRecording(), "isolated profile already has a recording");

  int engines = 0;
  int recordingUpdates = 0;
  QObject::connect(&mapCore, &sailfish::MapItem::engineCreated, [&] { ++engines; });
  QObject::connect(&mapCore, &sailfish::MapItem::recordingStatsChanged, [&] { ++recordingUpdates; });
  auto * routing = mapCore.routing();
  routing->setVoiceEnabled(false);
  location::GpsInfo fix;
  fix.m_source = location::EUser;
  fix.m_latitude = 23.130158;
  fix.m_longitude = 113.621144;
  fix.m_horizontalAccuracy = 5;
  fix.m_speed = 15;
  fix.m_timestamp = QDateTime::currentMSecsSinceEpoch() / 1000.0;
  routing->planRoute(sailfish::Routing::Vehicle,
                    {QVariantMap{{"lat", fix.m_latitude}, {"lon", fix.m_longitude}, {"name", "Start"}},
                     QVariantMap{{"lat", 23.137}, {"lon", 113.632}, {"name", QString::fromUtf8("测试目的地 🌍")}}});
  WaitFor([&] { return !routing->building(); }, 60000);
  Check(routing->canStart(), "offline route failed to build");
  routing->acceptDisclaimer();
  routing->start();
  WaitFor([&] { return routing->waitingForPosition(); });
  Check(!routing->navigating() && !routing->built(), "navigation started without a current position");
  Check(routing->errorTitle() == appInfo.localized("current_location_unknown_error_title"),
        "missing fix was reported as disabled location");
  // The backend has no phone or car window here. Waiting for a fix must still subscribe to GPS,
  // and the user's start request must survive the failed rebuild.
  static_cast<location::LocationObserver &>(mapCore).OnLocationUpdated(fix);
  Check(framework.GetCurrentPosition().has_value(), "headless location has no authoritative position");
  WaitFor([&] { return routing->navigating(); }, 60000);
  std::puts("MAP_POSITION_WAIT_RECOVERY_PASS headless-wait valid-fix rebuild automatic-navigation");
  mapCore.setSimulatingLocation(true);
  mapCore.startTrackRecording();
  WaitFor([&] { return !framework.IsTrackRecordingEmpty(); });

  QPointer<QQmlEngine> phoneEngine;
  for (int cycle = 0; cycle < 3; ++cycle)
  {
    Check(presentation.Show(), "full phone QML failed to load");
    for (auto * window : QGuiApplication::allWindows())
      window->hide();
    WaitFor([&] { return mapCore.window() != nullptr && framework.IsDrapeEngineCreated(); });
    Check(mapCore.parent() == nullptr && mapCore.parentItem() != nullptr, "phone changed backend QObject ownership");
    auto const point = framework.GetCurrentPosition();
    int const previousUpdates = recordingUpdates;
    double const previousRemaining = RemainingMeters(routing->NavigationSnapshot());
    Check(previousRemaining > 0, "active route has no remaining distance");
    auto * window = mapCore.window();
    auto * engine = static_cast<QQuickView *>(window)->engine();
    Check(!phoneEngine || phoneEngine == engine, "phone reopening replaced the retained QML engine");
    phoneEngine = engine;
    QPointer<QQuickWindow> phoneWindow(window);
    window->close();
    WaitFor([&] { return !presentation.isOpen(); });
    Check(phoneWindow.isNull() && phoneEngine, "phone closure did not release the view while retaining its engine");
    Check(mapCore.window() == nullptr && mapCore.parentItem() == nullptr && !framework.IsDrapeEngineCreated(),
          "window closure retained the phone renderer");
    Check(routing->navigating() && routing->HasBackgroundWork() && mapCore.trackRecording(),
          "phone closure stopped shared work");
    WaitFor([&]
    {
      return framework.GetCurrentPosition() != point && recordingUpdates > previousUpdates &&
             RemainingMeters(routing->NavigationSnapshot()) < previousRemaining - 1;
    });
    Check(!mapCore.recordingSummary().isEmpty(), "headless recording statistics stopped");
    Check(routing->NavigationSnapshot().value("state").toString() == "active", "headless guidance stopped");
  }
  Check(engines == 3, "unexpected renderer recreation count");
  Check(mapCore.saveAndStopTrackRecording(), "background recording could not be saved");
  mapCore.setSimulatingLocation(false);
  routing->close();
  Check(!routing->navigating() && !routing->active() && !mapCore.trackRecording(), "explicit stop retained work");
  Check(presentation.Show(), "phone failed to reopen after stop");
  for (auto * window : QGuiApplication::allWindows())
    window->hide();
  Check(!routing->active(), "phone reopening restored explicitly stopped navigation");
  presentation.Close();
  WaitFor([&] { return !bookmarksIO.busy() && !routing->HasBackgroundWork(); });
  Check(!framework.IsDrapeEngineCreated(), "final closure retained the renderer");
  sailfish::SailplayMapCanvas canvas(mapCore, presentation);
  auto const frame = [&]
  {
    QVariantMap result;
    QImage image;
    QSet<QRgb> colors;
    auto const fetch = [&]
    {
      result = canvas.Frame(QSize(640, 360));
      image = QImage::fromData(result.value("image").toByteArray(), "JPEG");
      colors.clear();
      if (image.isNull())
        return;
      for (int y = 0; y < image.height(); y += 16)
        for (int x = 0; x < image.width(); x += 16)
          colors.insert(image.pixel(x, y));
    };
    // Match the production host's 5 Hz requests, including during GeoClue's nested event loop.
    QTimer requests;
    QObject::connect(&requests, &QTimer::timeout, fetch);
    requests.start(200);
    fetch();
    WaitFor([&] { return colors.size() > 4; }, 60000);
    requests.stop();
    Check(!image.isNull() && image.width() == result.value("width").toInt() &&
          image.height() == result.value("height").toInt(), "canvas returned invalid pixels");
    Check(image.size() == QSize(640, 360), "canvas frame does not match the car viewport");
    std::fprintf(stderr, "MAP_CANVAS_FRAME width=%d height=%d colors=%d phone=%d\n",
                 image.width(), image.height(), colors.size(), presentation.isOpen());
  };
  frame();
  Check(!presentation.isOpen() && framework.IsDrapeEngineCreated(), "cold car canvas opened a phone view");
  fix.m_timestamp = QDateTime::currentMSecsSinceEpoch() / 1000.0;
  static_cast<location::LocationObserver &>(mapCore).OnLocationUpdated(fix);
  sailfish::SailplayMapBrowser browser(mapCore);
  browser.Invoke({{"command", "history"}});
  Check(browser.Snapshot().value("page") == "history", "destination history did not open");
  browser.Invoke({{"command", "categories"}});
  Check(!browser.Snapshot().value("rows").toList().isEmpty(), "offline categories are unavailable");
  browser.Invoke({{"command", "search"}, {"query", "23.137, 113.632"}});
  Check(browser.Snapshot().value("searching").toBool(), "search did not hide stale results");
  WaitFor([&] { return !browser.Snapshot().value("searching").toBool(); });
  auto searchRows = browser.Snapshot().value("rows").toList();
  Check(!searchRows.isEmpty(), "coordinate search returned no places");
  browser.Invoke({{"command", "select"}, {"id", searchRows.front().toMap().value("id")}});
  Check(mapCore.placePage()->open() && browser.Snapshot().value("page").toString().isEmpty(),
        "search selection did not open the authoritative place");
  browser.Invoke({{"command", "toggle-bookmark"}});
  Check(mapCore.placePage()->isBookmark(), "car bookmark did not use the phone bookmark manager");
  routing->routeToPlace();
  WaitFor([&] { return !routing->building(); }, 60000);
  Check(routing->canStart(), "search destination did not build an offline route");
  routing->close();
  auto & manager = framework.GetBookmarkManager();
  auto const category = manager.CreateBookmarkCategory("Car saved places", false);
  for (int index = 0; index < 45; ++index)
  {
    kml::BookmarkData data;
    kml::SetDefaultStr(data.m_name, "Saved place " + std::to_string(index));
    data.m_point = mercator::FromLatLon(23.137, 113.632);
    manager.GetEditSession().CreateBookmark(std::move(data), category);
  }
  browser.Invoke({{"command", "bookmark-groups"}});
  auto const groups = browser.Snapshot().value("rows").toList();
  auto const group = std::find_if(groups.begin(), groups.end(), [](QVariant const & value)
  { return value.toMap().value("title") == "Car saved places"; });
  Check(group != groups.end(), "saved bookmark category is absent");
  browser.Invoke({{"command", "select"}, {"id", group->toMap().value("id")}});
  Check(browser.Snapshot().value("rows").toList().size() == 40 && browser.Snapshot().value("next").toBool(),
        "bookmark first page did not respect its bound");
  browser.Invoke({{"command", "next"}});
  auto const saved = browser.Snapshot().value("rows").toList();
  Check(saved.size() == 5 && browser.Snapshot().value("previous").toBool(), "bookmark next page is incorrect");
  browser.Invoke({{"command", "select"}, {"id", saved.front().toMap().value("id")}});
  Check(mapCore.placePage()->isBookmark(), "bookmark selection did not open the saved place");
  browser.Invoke({{"command", "clear-place"}});
  Check(!mapCore.placePage()->open(), "car place close failed");
  browser.Invoke({{"command", "settings"}});
  browser.Invoke({{"command", "walking"}});
  Check(routing->routerType() == sailfish::Routing::Pedestrian, "route settings did not reach the backend");
  browser.Invoke({{"command", "vehicle"}});
  for (auto const & parameters : {QVariantMap{{"command", "search"}, {"query", QString(257, 'x')}},
                                 QVariantMap{{"command", "history"}, {"extra", "x"}},
                                 QVariantMap{{"command", "select"}, {"id", searchRows.front().toMap().value("id")}}})
  {
    bool rejected = false;
    try { browser.Invoke(parameters); }
    catch (std::invalid_argument const &) { rejected = true; }
    Check(rejected, "invalid or stale destination action was accepted");
  }
  browser.Invoke({{"command", "close"}});
  std::puts("MAP_DESTINATION_BROWSER_PASS offline-search select route bookmarks pagination settings stale-id");
  canvas.Touch("press", 0.5, 0.5);
  canvas.Touch("move", 0.6, 0.5);
  canvas.Touch("release", 0.6, 0.5);
  mapCore.zoomIn();
  frame();
  for (int cycle = 0; cycle < 3; ++cycle)
  {
    Check(presentation.Show(), "canvas prevented phone reopen");
    for (auto * window : QGuiApplication::allWindows()) window->hide();
    frame();
    Check(mapCore.window() && mapCore.window()->inherits("QQuickView"), "canvas displaced the phone viewport");
    presentation.Close();
    frame();
    Check(!presentation.isOpen() && mapCore.window() && framework.IsDrapeEngineCreated(),
          "phone closure stopped the car canvas");
    Check(!routing->active(), "canvas restored explicitly stopped navigation");
  }
  WaitFor([&] { return !framework.IsDrapeEngineCreated(); }, 5000);
  Check(mapCore.window() == nullptr, "expired canvas retained its offscreen window");
  std::puts("MAP_BACKEND_LIFECYCLE_PASS full-phone-qml window-close reopen same-core drape-release headless-gps "
            "offline-route-progress recording-statistics saved-recording explicit-stop car-canvas touch expiry");
  return EXIT_SUCCESS;
}
