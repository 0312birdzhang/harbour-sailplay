#ifndef SAILPLAY_DASHBOARD_WEATHER_H
#define SAILPLAY_DASHBOARD_WEATHER_H

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>
#include <QSet>
#include <QVariantList>
#include <cmath>

// Read the Weather app's cache without changing its current location or provider.
inline QVariantList dashboardWeatherLocations()
{
    const QDir directory(QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)
                         + QStringLiteral("/org.sailfishos/weather"));
    QVariantList result;
    QSet<QString> keys;
    for (const QString &name : directory.entryList(QStringList{QStringLiteral("*.json")}, QDir::Files)) {
        QFile file(directory.filePath(name));
        if (file.size() > 1024 * 1024 || !file.open(QIODevice::ReadOnly)) continue;
        const QJsonObject root = QJsonDocument::fromJson(file.readAll()).object();
        QJsonArray locations = root.value(QStringLiteral("savedLocations")).toArray();
        locations.prepend(root.value(QStringLiteral("currentLocation")));
        const QString provider = name.left(name.size() - 5);
        for (const QJsonValue &value : locations) {
            const QJsonObject location = value.toObject();
            const int id = location.value(QStringLiteral("locationId")).toInt();
            const QString city = location.value(QStringLiteral("city")).toString();
            const QString key = provider + QLatin1Char(':') + QString::number(id);
            if (id <= 0 || city.isEmpty() || keys.contains(key)) continue;
            keys.insert(key);
            const QJsonObject weather = location.value(QStringLiteral("weather")).toObject();
            const QJsonValue temperature = weather.value(QStringLiteral("temperature"));
            QVariantMap row = weather.toVariantMap();
            row.insert(QStringLiteral("key"), key);
            row.insert(QStringLiteral("city"), city);
            row.insert(QStringLiteral("country"), location.value(QStringLiteral("country")).toString());
            row.insert(QStringLiteral("provider"), provider);
            row.insert(QStringLiteral("populated"), weather.value(QStringLiteral("populated")).toBool()
                && temperature.isDouble() && std::isfinite(temperature.toDouble()));
            result.append(row);
        }
    }
    return result;
}

#endif
