#pragma once

#include "themeschedule.h"
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QSettings>
#include <cerrno>
#include <sys/file.h>

class SailplayThemeSettings
{
public:
    enum Mode { Headlights, Ambience, Custom };
    static QString configPath() {
        return QDir::homePath() + QStringLiteral("/.config/sailplay/theme.ini");
    }
    static QString vehiclePath() { return QStringLiteral("/run/sailplay-vehicle-theme/state.ini"); }
    explicit SailplayThemeSettings(const QString &vehicleStatePath = vehiclePath()) : m_vehiclePath(vehicleStatePath) {}
    QString dayStart() const { return themeTime(QStringLiteral("DayStart"), QStringLiteral("07:00")); }
    QString nightStart() const { return themeTime(QStringLiteral("NightStart"), QStringLiteral("19:00")); }
    bool dayTheme() const { return m_dayTheme; }
    int mode() const {
        QSettings settings(configPath(), QSettings::IniFormat);
        const QString value = settings.value(QStringLiteral("Mode")).toString();
        if (value == QStringLiteral("headlights")) return Headlights;
        if (value == QStringLiteral("ambience")) return Ambience;
        if (value == QStringLiteral("custom")) return Custom;
        return settings.value(QStringLiteral("FollowAmbience"), true).toBool() ? Ambience : Custom;
    }
    bool followAmbience() const { return mode() == Ambience; }
    bool update() {
        const QString day = dayStart(), night = nightStart();
        const QTime now = QTime::currentTime();
        const QTime d = QTime::fromString(day, QStringLiteral("HH:mm"));
        const QTime n = QTime::fromString(night, QStringLiteral("HH:mm"));
        const int selected = mode();
        const int vehicleNight = selected == Headlights ? vehicleNightMode() : -1;
        const bool daytime = selected == Custom
            ? day != night && sailplayDayAt(now.hour()*60+now.minute(), d.hour()*60+d.minute(), n.hour()*60+n.minute())
            : vehicleNight >= 0 ? vehicleNight == 0 : ambienceColorScheme() == 1;
        const QString schedule = QString::number(selected) + QLatin1Char('|') + day + QLatin1Char('|') + night;
        if (daytime == m_dayTheme && schedule == m_schedule) return false;
        m_dayTheme = daytime;
        m_schedule = schedule;
        return true;
    }

private:
    int vehicleNightMode() const {
        QSettings settings(m_vehiclePath, QSettings::IniFormat);
        const QString value = settings.value(QStringLiteral("Vehicle/NightMode")).toString();
        if (value != QStringLiteral("true") && value != QStringLiteral("false")) return -1;
        const QByteArray session = settings.value(QStringLiteral("Vehicle/Session")).toByteArray();
        if (session.isEmpty()) return -1;
        QFile owner(QFileInfo(m_vehiclePath).dir().filePath(QStringLiteral("session.lock")));
        if (!owner.open(QIODevice::ReadOnly)) return -1;
        // The protocol holds this stable inode exclusively for the session.
        // A read-only sandbox can check the lock even when /proc is restricted.
        if (flock(owner.handle(), LOCK_SH | LOCK_NB) == 0) {
            flock(owner.handle(), LOCK_UN);
            return -1;
        }
        if (errno != EWOULDBLOCK && errno != EAGAIN) return -1;
        if (owner.readAll() != session) return -1;
        return value == QStringLiteral("true") ? 1 : 0;
    }
    QString themeTime(const QString &key, const QString &fallback) const {
        QSettings settings(configPath(), QSettings::IniFormat);
        const QTime time = QTime::fromString(settings.value(key, fallback).toString(), QStringLiteral("HH:mm"));
        return time.isValid() ? time.toString(QStringLiteral("HH:mm")) : fallback;
    }
    // Silica schemes are 0 for light-on-dark and 1 for dark-on-light.
    // Cache the query until the user's dconf database changes.
    int ambienceColorScheme() {
        const QDateTime stamp = QFileInfo(QDir::homePath() + QStringLiteral("/.config/dconf/user")).lastModified();
        if (m_colorScheme < 0 || stamp != m_dconfStamp) {
            m_dconfStamp = stamp;
            QProcess dconf;
            dconf.start(QStringLiteral("dconf"), {QStringLiteral("read"), QStringLiteral("/desktop/jolla/theme/color_scheme")});
            if (dconf.waitForFinished(1000) && dconf.exitCode() == 0) {
                bool ok = false;
                const int scheme = dconf.readAllStandardOutput().trimmed().toInt(&ok);
                m_colorScheme = ok ? scheme : 0;
            } else if (m_colorScheme < 0) {
                m_colorScheme = 0;
            }
        }
        return m_colorScheme;
    }
    bool m_dayTheme = false;
    QString m_schedule;
    int m_colorScheme = -1;
    QDateTime m_dconfStamp;
    QString m_vehiclePath;
};
