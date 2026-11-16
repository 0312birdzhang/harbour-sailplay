#include "diagnosticslogging.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QMutex>
#include <QMutexLocker>
#include <QSettings>
#include <QThread>
#include <cstdio>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

namespace {
constexpr qint64 maxBytes = 4 * 1024 * 1024;
constexpr int backupCount = 5;
QMutex logMutex;
QtMessageHandler previousHandler = nullptr;
bool loggingActive = false;
double lastSync = 0;

double monotonicSeconds()
{
    timespec stamp;
    clock_gettime(CLOCK_MONOTONIC, &stamp);
    return stamp.tv_sec + stamp.tv_nsec / 1e9;
}

bool rotateLog(const QString &path)
{
    const QString oldest = path + QStringLiteral(".%1").arg(backupCount);
    if (QFile::exists(oldest) && !QFile::remove(oldest)) return false;
    for (int index = backupCount - 1; index > 0; --index) {
        const QString source = path + QStringLiteral(".%1").arg(index);
        if (QFile::exists(source) && !QFile::rename(source, path + QStringLiteral(".%1").arg(index + 1)))
            return false;
    }
    return QFile::rename(path, path + QStringLiteral(".1"));
}

bool appendRecord(const QString &message, const char *level, bool sync)
{
    const QString directory = QDir::homePath() + QStringLiteral("/.local/share/sailplay/logs");
    if (!QDir().mkpath(directory)) return false;
    if (::chmod(QFile::encodeName(directory).constData(), 0700)) return false;
    const QString path = directory + QStringLiteral("/mobile-ui.log");
    const int flags = O_CREAT | O_NOFOLLOW | O_CLOEXEC;
    const int lock = ::open(QFile::encodeName(path + QStringLiteral(".lock")).constData(), flags | O_RDWR, 0600);
    if (lock < 0) return false;
    if (::fchmod(lock, 0600) || ::flock(lock, LOCK_EX)) {
        ::close(lock);
        return false;
    }
    const double now = monotonicSeconds();
    QString text = message;
    text.replace(QLatin1Char('\r'), QStringLiteral("\\r"));
    text.replace(QLatin1Char('\n'), QStringLiteral("\\n"));
    const QDateTime wallTime = QDateTime::currentDateTime();
    const int offsetMinutes = wallTime.offsetFromUtc() / 60;
    const QString timestamp = wallTime.toString(QStringLiteral("yyyy-MM-ddTHH:mm:ss.zzz"))
        + QStringLiteral("%1%2:%3").arg(offsetMinutes < 0 ? QLatin1Char('-') : QLatin1Char('+'))
            .arg(qAbs(offsetMinutes) / 60, 2, 10, QLatin1Char('0'))
            .arg(qAbs(offsetMinutes) % 60, 2, 10, QLatin1Char('0'));
    QByteArray record = QStringLiteral("%1 mono=%2 pid=%3 thread=%4 component=mobile-ui %5 %6\n")
        .arg(timestamp)
        .arg(now, 0, 'f', 6).arg(::getpid())
        .arg(quintptr(QThread::currentThreadId()), 0, 16).arg(QString::fromLatin1(level), text).toUtf8();
    if (record.size() > 16384) {
        record = QString::fromUtf8(record.left(16360)).toUtf8();
        record += " [truncated]\n";
    }
    int fd = ::open(QFile::encodeName(path).constData(), flags | O_WRONLY | O_APPEND, 0600);
    struct stat info;
    if (fd >= 0 && ::fstat(fd, &info) == 0 && info.st_size && info.st_size + record.size() > maxBytes) {
        ::close(fd);
        fd = -1;
        if (rotateLog(path))
            fd = ::open(QFile::encodeName(path).constData(), flags | O_WRONLY | O_APPEND, 0600);
    }
    bool success = false;
    if (fd >= 0) {
        ::fchmod(fd, 0600);
        QFile output;
        if (output.open(fd, QIODevice::WriteOnly | QIODevice::Append, QFileDevice::AutoCloseHandle)) {
            success = output.write(record) == record.size() && output.flush();
            if (success && (sync || now - lastSync >= 1)) {
                success = ::fsync(fd) == 0;
                lastSync = now;
            }
        } else {
            ::close(fd);
        }
    }
    ::close(lock);
    return success;
}

void mobileMessage(QtMsgType type, const QMessageLogContext &context, const QString &message)
{
    static thread_local bool writing = false;
    const char *level = "INFO";
    switch (type) {
    case QtDebugMsg: level = "DEBUG"; break;
    case QtWarningMsg: level = "WARNING"; break;
    case QtCriticalMsg: level = "ERROR"; break;
    case QtFatalMsg: level = "FATAL"; break;
    default: break;
    }
    if (!writing) {
        writing = true;
        QMutexLocker locker(&logMutex);
        if (diagnosticLoggingEnabled()) {
            if (!loggingActive) {
                QFile version(QStringLiteral("/opt/sailplay/version"));
                const QString identity = version.open(QIODevice::ReadOnly)
                    ? QString::fromUtf8(version.readAll()).trimmed() : QStringLiteral("unknown");
                QFile boot(QStringLiteral("/proc/sys/kernel/random/boot_id"));
                const QString bootId = boot.open(QIODevice::ReadOnly)
                    ? QString::fromUtf8(boot.readAll()).trimmed() : QStringLiteral("unknown");
                loggingActive = appendRecord(QStringLiteral("diagnostics enabled boot=%1 version=%2").arg(bootId, identity), "INFO", true);
            }
            appendRecord(message, level, type == QtCriticalMsg || type == QtFatalMsg);
        } else {
            loggingActive = false;
        }
        writing = false;
    }
    if (previousHandler) previousHandler(type, context, message);
    else std::fprintf(stderr, "%s\n", qPrintable(message));
}
}

QString diagnosticsConfigPath()
{
    const QByteArray overridePath = qgetenv("SAILPLAY_DIAGNOSTICS_CONFIG");
    return overridePath.isEmpty() ? QDir::homePath() + QStringLiteral("/.config/sailplay/diagnostics.ini")
                                  : QString::fromLocal8Bit(overridePath);
}

bool diagnosticLoggingEnabled()
{
    QSettings settings(diagnosticsConfigPath(), QSettings::IniFormat);
    settings.sync();
    if (settings.status() != QSettings::NoError) return false;
    const QString value = settings.value(QStringLiteral("Diagnostics/enabled"), false).toString().toLower();
    return value == QStringLiteral("true") || value == QStringLiteral("1")
        || value == QStringLiteral("yes") || value == QStringLiteral("on");
}

void installMobileDiagnostics()
{
    previousHandler = qInstallMessageHandler(mobileMessage);
}
