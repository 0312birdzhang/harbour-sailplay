#include "navigationhost.h"

#include <QCoreApplication>
#include <QDBusArgument>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QBuffer>
#include <QImageReader>
#include <QSaveFile>
#include <QSet>
#include <QSignalBlocker>
#include <QVector>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

namespace {
qulonglong boottimeMs()
{
    timespec now;
    clock_gettime(CLOCK_BOOTTIME, &now);
    return qulonglong(now.tv_sec) * 1000 + now.tv_nsec / 1000000;
}

bool unsignedInteger(const QVariant &value)
{
    const QVariant::Type type = value.type();
    return type == QVariant::UInt || type == QVariant::ULongLong
        || ((type == QVariant::Int || type == QVariant::LongLong) && value.toLongLong() >= 0);
}

bool validGuidance(const QVariantMap &value)
{
    const QSet<QString> fields = {QStringLiteral("state"), QStringLiteral("mode"), QStringLiteral("maneuver"),
        QStringLiteral("exitNumber"), QStringLiteral("drivingSide"), QStringLiteral("nextDistanceMeters"),
        QStringLiteral("remainingDistanceMeters"), QStringLiteral("remainingSeconds"), QStringLiteral("currentRoad"),
        QStringLiteral("nextRoad"), QStringLiteral("destination"), QStringLiteral("updatedMs")};
    const QStringList keys = value.keys();
    if (QSet<QString>::fromList(keys) != fields) return false;
    const QMap<QString, QStringList> enums = {
        {QStringLiteral("state"), {QStringLiteral("idle"), QStringLiteral("active"), QStringLiteral("unavailable"),
                                  QStringLiteral("stopped"), QStringLiteral("arrived")}},
        {QStringLiteral("mode"), {QStringLiteral("driving"), QStringLiteral("walking"), QStringLiteral("cycling"), QStringLiteral("transit")}},
        {QStringLiteral("drivingSide"), {QStringLiteral("left"), QStringLiteral("right")}},
        {QStringLiteral("maneuver"), {QStringLiteral("unknown"), QStringLiteral("continue"), QStringLiteral("slight-left"),
            QStringLiteral("slight-right"), QStringLiteral("turn-left"), QStringLiteral("turn-right"), QStringLiteral("sharp-left"),
            QStringLiteral("sharp-right"), QStringLiteral("uturn"), QStringLiteral("roundabout-enter"), QStringLiteral("roundabout-exit"),
            QStringLiteral("roundabout-continue"), QStringLiteral("exit-left"), QStringLiteral("exit-right"), QStringLiteral("arrive")}}
    };
    for (auto entry = enums.constBegin(); entry != enums.constEnd(); ++entry) {
        if (value.value(entry.key()).type() != QVariant::String || !entry.value().contains(value.value(entry.key()).toString()))
            return false;
    }
    for (const QString &key : {QStringLiteral("updatedMs"), QStringLiteral("exitNumber"), QStringLiteral("remainingSeconds")}) {
        if (!unsignedInteger(value.value(key))) return false;
    }
    if (value.value(QStringLiteral("exitNumber")).toULongLong() > 0xffffffff) return false;
    for (const QString &key : {QStringLiteral("nextDistanceMeters"), QStringLiteral("remainingDistanceMeters")}) {
        const QVariant number = value.value(key);
        if ((!unsignedInteger(number) && number.type() != QVariant::Double)
            || !std::isfinite(number.toDouble()) || number.toDouble() < 0) return false;
    }
    for (const QString &key : {QStringLiteral("currentRoad"), QStringLiteral("nextRoad"), QStringLiteral("destination")}) {
        const QVariant text = value.value(key);
        if (text.type() != QVariant::String || text.toString().toUcs4().size() > 1024 || text.toString().contains(QChar(0))) return false;
    }
    return value.value(QStringLiteral("updatedMs")).toULongLong() <= boottimeMs();
}

QString translated(const char *message)
{
    return QCoreApplication::translate("Sailplay", message);
}

QVariantMap clearedGuidance(const QVariantMap &value, const QString &state)
{
    QVariantMap result = value;
    result[QStringLiteral("state")] = state;
    result[QStringLiteral("mode")] = QStringLiteral("driving");
    result[QStringLiteral("maneuver")] = QStringLiteral("unknown");
    result[QStringLiteral("drivingSide")] = QStringLiteral("right");
    result[QStringLiteral("exitNumber")] = uint(0);
    result[QStringLiteral("nextDistanceMeters")] = 0.0;
    result[QStringLiteral("remainingDistanceMeters")] = 0.0;
    result[QStringLiteral("remainingSeconds")] = qulonglong(0);
    for (const QString &key : {QStringLiteral("currentRoad"), QStringLiteral("nextRoad"), QStringLiteral("destination")})
        result[key] = QString();
    return result;
}
}

SailplayNavigationHost::SailplayNavigationHost(const QString &runtime, QObject *parent)
    : QObject(parent), m_session(this)
{
    const QString directory = runtime.isEmpty() ? QString::fromUtf8(qgetenv("XDG_RUNTIME_DIR")) : runtime;
    m_directory = QDir(directory).filePath(QStringLiteral("sailplay-navigation"));
    m_filename = QDir(m_directory).filePath(QStringLiteral("sailplay-sdk-%1.json").arg(getpid()));
    QFile boot(QStringLiteral("/proc/sys/kernel/random/boot_id"));
    if (boot.open(QIODevice::ReadOnly)) m_bootId = QString::fromLatin1(boot.readAll()).trimmed();
    QFile process(QStringLiteral("/proc/self/stat"));
    if (process.open(QIODevice::ReadOnly)) {
        const QByteArray data = process.readAll();
        m_startTicks = QString::fromLatin1(data.mid(data.lastIndexOf(')') + 2).split(' ').value(19));
    }
    connect(&m_session, &SailplaySession::stateChanged, this, &SailplayNavigationHost::receiveState);
    connect(&m_session, &SailplaySession::readyChanged, this, [this](bool ready) {
        if (ready && m_session.applicationId() != m_declaration.applicationId) {
            m_session.close();
            fail(translated("Navigation provider identity does not match its desktop declaration"));
            return;
        }
        if (ready) m_session.setActive(m_active);
        else resetMap();
        publish();
        emit changed();
    });
    connect(&m_session, &SailplaySession::errorOccurred, this,
        [this](const QString &, const QString &message) { fail(message); });
    connect(&m_session, &SailplaySession::requestFinished, this,
        [this](qulonglong request, qulonglong, const QVariantMap &result, const QString &error, const QString &message) {
            if (request == m_mapRequest) {
                m_mapRequest = 0;
                if (error.isEmpty() && m_active) receiveMap(result);
                else if (!error.isEmpty()) { m_mapImage = QImage(); emit mapChanged(); }
            }
            if (request == m_touchRequest) {
                m_touchRequest = 0;
                sendTouch();
            }
            if (!error.isEmpty()) { m_error = message; emit changed(); }
        });
    connect(&m_heartbeat, &QTimer::timeout, this, &SailplayNavigationHost::publish);
    m_heartbeat.start(1000);
    connect(&m_mapTimer, &QTimer::timeout, this, &SailplayNavigationHost::requestMap);
    m_mapTimer.start(200);
}

SailplayNavigationHost::~SailplayNavigationHost()
{
    close();
}

void SailplayNavigationHost::open(const SailplayApplication &declaration, const QString &name)
{
    if (!declaration.applicationId.isEmpty()
        && declaration.presentationId() == m_declaration.presentationId() && m_error.isEmpty()) return;
    close();
    m_declaration = declaration;
    m_name = name;
    m_error.clear();
    if (!declaration.navigationTemplate()) {
        fail(translated("Navigation provider returned invalid guidance"));
        return;
    }
    m_session.open(declaration.service, declaration.path, QStringLiteral("car"), {QStringLiteral("navigation")});
    emit changed();
}

void SailplayNavigationHost::setActive(bool active)
{
    m_active = active;
    if (!active) {
        m_touches.clear();
        if (mapAvailable()) m_session.invoke(QStringLiteral("navigation.map.touch"),
            {{QStringLiteral("phase"), QStringLiteral("cancel")}, {QStringLiteral("x"), 0.0}, {QStringLiteral("y"), 0.0}});
    }
    if (m_session.ready()) m_session.setActive(active);
}

void SailplayNavigationHost::close()
{
    const QSignalBlocker blocker(&m_session);
    m_session.close();
    resetMap();
    removeExport();
    m_guidance.clear();
    m_declaration = SailplayApplication();
    m_name.clear();
    m_error.clear();
    emit changed();
}

void SailplayNavigationHost::stopNavigation()
{
    if (m_session.ready()) m_session.invoke(QStringLiteral("navigation.stop"));
}

void SailplayNavigationHost::configureMap(int width, int height)
{
    m_mapSize = QSize(qBound(64, width, 1920), qBound(64, height, 1920));
}

void SailplayNavigationHost::requestMap()
{
    if (!m_active || !mapAvailable() || m_mapSize.isEmpty() || m_mapRequest) return;
    m_mapRequest = m_session.invoke(QStringLiteral("navigation.map.frame"),
        {{QStringLiteral("width"), m_mapSize.width()}, {QStringLiteral("height"), m_mapSize.height()}});
}

void SailplayNavigationHost::resetMap()
{
    m_mapRequest = 0;
    m_touchRequest = 0;
    m_touches.clear();
    m_mapImage = QImage();
    m_mapState.clear();
    emit mapChanged();
}

void SailplayNavigationHost::receiveMap(const QVariantMap &result)
{
    const auto reject = [this] {
        m_mapImage = QImage();
        m_mapState.clear();
        emit mapChanged();
        fail(translated("Navigation provider returned invalid map data"));
    };
    const QVariant data = result.value(QStringLiteral("image"));
    if (data.type() != QVariant::ByteArray || data.toByteArray().size() > 4 * 1024 * 1024) {
        reject();
        return;
    }
    QByteArray bytes = data.toByteArray();
    if (bytes.isEmpty()) return;
    QBuffer buffer(&bytes);
    buffer.open(QIODevice::ReadOnly);
    QImageReader reader(&buffer, "JPEG");
    const QSize size = reader.size();
    if (size.width() < 1 || size.height() < 1 || size.width() > 1920 || size.height() > 1920
        || size.width() != result.value(QStringLiteral("width")).toInt()
        || size.height() != result.value(QStringLiteral("height")).toInt()) {
        reject();
        return;
    }
    const QImage image = reader.read();
    if (image.isNull()) {
        reject();
        return;
    }
    if (m_mapImage.isNull())
        std::fprintf(stderr, "carui: navigation map ready app=%s width=%d height=%d\n",
            qPrintable(applicationId()), image.width(), image.height());
    m_mapImage = image;
    m_mapState = qdbus_cast<QVariantMap>(result.value(QStringLiteral("state")));
    m_error.clear();
    emit mapChanged();
    emit changed();
}

void SailplayNavigationHost::mapTouch(const QString &phase, double x, double y)
{
    if (!m_active || !mapAvailable() || !mapReady() || !std::isfinite(x) || !std::isfinite(y)
        || x < 0 || x > 1 || y < 0 || y > 1
        || !QStringList{QStringLiteral("press"), QStringLiteral("move"), QStringLiteral("release"), QStringLiteral("cancel")}.contains(phase)) return;
    const QVariantMap touch = {{QStringLiteral("phase"), phase}, {QStringLiteral("x"), x}, {QStringLiteral("y"), y}};
    if (phase == QStringLiteral("move") && !m_touches.isEmpty()
        && m_touches.back().value(QStringLiteral("phase")) == QStringLiteral("move")) m_touches.back() = touch;
    else if (m_touches.size() < 32) m_touches.enqueue(touch);
    else { m_touches.clear(); m_touches.enqueue({{QStringLiteral("phase"), QStringLiteral("cancel")},
        {QStringLiteral("x"), 0.0}, {QStringLiteral("y"), 0.0}}); }
    sendTouch();
}

void SailplayNavigationHost::sendTouch()
{
    if (m_touchRequest || m_touches.isEmpty() || !m_active || !mapAvailable()) return;
    m_touchRequest = m_session.invoke(QStringLiteral("navigation.map.touch"), m_touches.dequeue());
}

void SailplayNavigationHost::mapControl(const QString &command)
{
    if (m_active && mapAvailable()) m_session.invoke(QStringLiteral("navigation.map.control"),
        {{QStringLiteral("command"), command}});
}

void SailplayNavigationHost::receiveState()
{
    if (m_session.revision() == 0) {
        m_guidance.clear();
        removeExport();
    } else {
        const QVariantMap value = qdbus_cast<QVariantMap>(m_session.state().value(QStringLiteral("navigation")));
        if (!validGuidance(value)) {
            m_session.close();
            fail(translated("Navigation provider returned invalid guidance"));
            return;
        }
        m_guidance = value.value(QStringLiteral("state")) == QStringLiteral("active")
            ? value : clearedGuidance(value, value.value(QStringLiteral("state")).toString());
        m_error.clear();
        publish();
    }
    emit changed();
}

void SailplayNavigationHost::publish()
{
    if (!m_session.ready() || m_guidance.isEmpty()) {
        removeExport();
        return;
    }
    const qulonglong now = boottimeMs();
    if (m_guidance.value(QStringLiteral("state")) == QStringLiteral("active")
        && now - m_guidance.value(QStringLiteral("updatedMs")).toULongLong() > 10000) {
        m_guidance = clearedGuidance(m_guidance, QStringLiteral("unavailable"));
        emit changed();
    }
    if (!QDir(m_directory).isAbsolute() || m_bootId.isEmpty() || m_startTicks.isEmpty()
        || (mkdir(qPrintable(m_directory), 0700) != 0 && errno != EEXIST)) {
        fail(translated("Could not publish navigation guidance"));
        return;
    }
    struct stat info;
    if (lstat(qPrintable(m_directory), &info) != 0 || !S_ISDIR(info.st_mode) || info.st_uid != getuid()
        || (info.st_mode & 0077) != 0) {
        fail(translated("Could not publish navigation guidance"));
        return;
    }
    QFile existing(m_filename);
    if (QFileInfo(existing).isSymLink()
        || (existing.exists() && (!existing.open(QIODevice::ReadOnly) || existing.readAll() != m_lastExport))) {
        fail(translated("Could not publish navigation guidance"));
        return;
    }
    QVariantMap navigation = m_guidance;
    // JSON's double representation cannot preserve every D-Bus uint64 value.
    navigation[QStringLiteral("remainingSeconds")] = QString::number(navigation.value(QStringLiteral("remainingSeconds")).toULongLong());
    const QVariantMap envelope = {
        {QStringLiteral("schema"), 2}, {QStringLiteral("source"), QStringLiteral("sailplay-sdk")},
        {QStringLiteral("pid"), qlonglong(getpid())}, {QStringLiteral("startTicks"), m_startTicks},
        {QStringLiteral("bootId"), m_bootId}, {QStringLiteral("applicationId"), m_declaration.applicationId},
        {QStringLiteral("appKey"), QString::fromLatin1(m_declaration.applicationId.toUtf8().toBase64())},
        {QStringLiteral("service"), m_declaration.service}, {QStringLiteral("instanceId"), m_session.instanceId()},
        {QStringLiteral("sequence"), QString::number(m_session.revision())},
        {QStringLiteral("heartbeatMs"), now}, {QStringLiteral("navigation"), navigation}
    };
    const QByteArray data = QJsonDocument(QJsonObject::fromVariantMap(envelope)).toJson(QJsonDocument::Compact);
    QSaveFile output(m_filename);
    if (!output.open(QIODevice::WriteOnly) || !output.setPermissions(QFile::ReadOwner | QFile::WriteOwner)
        || output.write(data) != data.size() || !output.commit()) {
        fail(translated("Could not publish navigation guidance"));
        return;
    }
    m_lastExport = data;
}

void SailplayNavigationHost::removeExport()
{
    QFile file(m_filename);
    if (!m_lastExport.isEmpty() && !QFileInfo(file).isSymLink() && file.open(QIODevice::ReadOnly)
        && file.readAll() == m_lastExport) {
        file.close();
        file.remove();
    }
    m_lastExport.clear();
}

void SailplayNavigationHost::fail(const QString &message)
{
    m_error = message;
    removeExport();
    emit changed();
}
