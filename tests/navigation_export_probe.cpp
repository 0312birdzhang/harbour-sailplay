// Standalone QtCore probe for the Organic Maps exporter (no route or GPS needed).
#include "sailfish/navigation_export.hpp"

#include <QCoreApplication>
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QTemporaryDir>
#include <QTimer>

#include <cstdio>

int main(int argc, char ** argv)
{
  QCoreApplication app(argc, argv);
  QTemporaryDir runtime;
  if (!runtime.isValid())
    return 1;
  qputenv("XDG_RUNTIME_DIR", runtime.path().toUtf8());
  qputenv("CARLIFE_APP_KEY", "b3JnYW5pY21hcHM=");
  auto const path = runtime.path() + QStringLiteral("/sailplay-navigation/organicmaps-%1.json")
                                       .arg(QCoreApplication::applicationPid());
  auto read = [&path]
  {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
      return QJsonObject();
    return QJsonDocument::fromJson(file.readAll()).object();
  };
  qunsetenv("SAILPLAY_NAVIGATION_EXPORT");
  {
    sailfish::NavigationExport disabled;
    disabled.Publish({{"state", "active"}});
    if (QFile::exists(path))
      return 2;
  }
  qputenv("SAILPLAY_NAVIGATION_EXPORT", "1");
  {
    sailfish::NavigationExport exporter;
    auto const idle = read();
    if (idle.value("navigation").toObject().value("state").toString() != "idle")
      return 3;
    exporter.Publish({{"state", "active"}, {"turn", 5}, {"currentRoad", QString::fromUtf8("南京路")}});
    auto const first = read();
    QEventLoop loop;
    QTimer::singleShot(1300, &loop, &QEventLoop::quit);
    loop.exec();
    auto const next = read();
    if (first.value("updatedMs") != next.value("updatedMs") ||
        first.value("sequence") != next.value("sequence") ||
        next.value("heartbeatMs").toDouble() <= first.value("heartbeatMs").toDouble())
      return 4;
    auto const permissions = QFileInfo(path).permissions();
    if (permissions & (QFile::ReadGroup | QFile::WriteGroup | QFile::ReadOther | QFile::WriteOther))
      return 5;
    exporter.Publish({{"state", "arrived"}});
    if (read().value("navigation").toObject().contains("turn"))
      return 6;
  }
  if (QFile::exists(path))
    return 7;
  std::puts("NAVIGATION_EXPORT_OK: opt-in, atomic snapshot, heartbeat, terminal state, cleanup");
  return 0;
}
