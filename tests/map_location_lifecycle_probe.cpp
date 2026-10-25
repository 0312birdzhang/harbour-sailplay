// Runs against the real Qt GeoClue adapter; injects fixes without waiting for GPS.
#include "platform/location_service/qt_location_service.hpp"
#include <QCoreApplication>
#include <QDateTime>
#include <QGeoCoordinate>
#include <QGeoPositionInfo>
#include <cstdio>

struct Observer : location::LocationObserver
{
  int fixes = 0;
  int errors = 0;
  location::TLocationSource source = location::EUndefined;
  void OnLocationError(location::TLocationError) override { ++errors; }
  void OnLocationUpdated(location::GpsInfo const & info) override { ++fixes; source = info.m_source; }
};

int main(int argc, char ** argv)
{
  QCoreApplication app(argc, argv);
  Observer observer;
  QtLocationService service(observer, "geoclue");
  QGeoPositionInfo fix(QGeoCoordinate(23, 113), QDateTime::currentDateTimeUtc());
  fix.setAttribute(QGeoPositionInfo::HorizontalAccuracy, 5);
  service.OnLocationUpdate(fix);
  service.OnErrorOccurred(QGeoPositionInfoSource::AccessError);
  if (observer.fixes || observer.errors) return 1;
  service.Start();
  service.OnLocationUpdate(fix);
  if (observer.fixes != 1 || observer.source != location::EGeoClue) return 2;
  service.Stop();
  int const errors = observer.errors;
  service.OnLocationUpdate(fix);
  service.OnErrorOccurred(QGeoPositionInfoSource::AccessError);
  if (observer.fixes != 1 || observer.errors != errors) return 3;
  service.Start();
  service.OnLocationUpdate(fix);
  service.Stop();
  if (observer.fixes != 2) return 4;
  std::puts("GEOCLUE_STOP_QUEUED_CALLBACK_RESTART_OK");
}
