#include <QGuiApplication>
#include <QTranslator>
#include <QLocale>
#include <QQmlApplicationEngine>
#include <QQmlComponent>
#include <QQmlContext>
#include <QUrl>
#include <QQuickWindow>
#include <QQuickView>
#include <QObject>
#include <QProcess>
#include <QFile>
#include <QFileInfo>
#include <QDir>
#include <QDateTime>
#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusPendingCall>
#include <QDBusVariant>
#include <QDBusArgument>
#include <QDBusObjectPath>
#include <QDBusPendingCallWatcher>
#include <functional>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <cerrno>
#include <QVariantList>
#include <QVariantMap>
#include <QStringList>
#include <QSet>
#include <QTimer>
#include <algorithm>
#include <cstdio>
#include <sailfishapp.h>

static const char *kSystemConfig = "/opt/sailplay/carui-apps.conf";

struct AppInfo {
    QString category;
    QString appId;
    QString name;
    QString exec;
    QString icon;
};

// An installed application: id = desktop-file basename. fullExec apps run
// their Exec line verbatim ("flatpak-runner com.qq.QQ", "apkd-launcher …" —
// runner-style commands whose arguments matter); everything else runs the
// extracted plain binary (sailjail/invoker would wire the app to lipstick
// instead of our virtual display imira-comp-0).
struct AvailableApp {
    QString id;
    QString name;
    QString exec;
    QString icon;
};
static QVector<AvailableApp> g_available;

static QString userConfigPath()
{
    return QDir::home().filePath(QStringLiteral(".config/carlife/carui-apps.conf"));
}

static QString recentPath()
{
    return QDir::home().filePath(QStringLiteral(".config/carlife/carui-recent"));
}

// Resolve a desktop Icon= entry to a loadable image path.
static QString resolveIcon(const QString &iconName)
{
    if (iconName.startsWith(QLatin1Char('/')))
        return QFile::exists(iconName) ? iconName : QString();
    if (iconName.isEmpty())
        return QString();
    const QStringList sizes = {
        QStringLiteral("86x86"), QStringLiteral("128x128"),
        QStringLiteral("108x108"), QStringLiteral("172x172"),
        QStringLiteral("512x512")
    };
    for (const QString &s : sizes) {
        const QString p = QStringLiteral("/usr/share/icons/hicolor/") + s
                          + QStringLiteral("/apps/") + iconName
                          + QStringLiteral(".png");
        if (QFile::exists(p))
            return p;
    }
    QDir theme(QStringLiteral("/usr/share/themes/sailfish-default/silica"));
    for (const QString &z : theme.entryList(QStringList() << QStringLiteral("z*"),
                                            QDir::Dirs)) {
        const QString p = theme.filePath(z) + QStringLiteral("/icons/")
                          + iconName + QStringLiteral(".png");
        if (QFile::exists(p))
            return p;
    }
    return QString();
}

static bool parseDesktopFile(const QString &path, QString *name, QString *exec,
                             bool *hidden, QString *icon)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
        return false;
    *name = QFileInfo(path).completeBaseName();
    *exec = QString();
    *icon = QString();
    *hidden = false;
    QString logicalId;
    QString translationCatalog;
    while (!f.atEnd()) {
        QString line = QString::fromUtf8(f.readLine()).trimmed();
        int eq = line.indexOf(QLatin1Char('='));
        if (eq < 0)
            continue;
        // some generated desktops (flatpak-runner-autogen) write "Name = x"
        QString key = line.left(eq).trimmed();
        QString val = line.mid(eq + 1).trimmed();
        if (key == QStringLiteral("Name"))
            *name = val;
        else if (key == QStringLiteral("X-MeeGo-Logical-Id"))
            logicalId = val;
        else if (key == QStringLiteral("X-MeeGo-Translation-Catalog"))
            translationCatalog = val;
        else if (key == QStringLiteral("Exec") && exec->isEmpty())
            *exec = val;
        else if (key == QStringLiteral("Icon") && icon->isEmpty())
            *icon = val;
        else if ((key == QStringLiteral("NoDisplay")
                  || key == QStringLiteral("Hidden")) && val == QStringLiteral("true"))
            *hidden = true;
    }
    if (!logicalId.isEmpty() && !translationCatalog.isEmpty()) {
        QTranslator translator;
        const QString locale = QLocale::system().name();
        const QString file = QStringLiteral("/usr/share/translations/")
                           + translationCatalog + QLatin1Char('-') + locale
                           + QStringLiteral(".qm");
        if (translator.load(file)) {
            const QByteArray id = logicalId.toUtf8();
            const QString localized = translator.translate("", id.constData());
            if (!localized.isEmpty())
                *name = localized;
        }
    }
    return !exec->isEmpty();
}

// Native desktops carry an absolute binary in Exec ("sailjail -p x
// /usr/bin/app"); runner-style desktops ("flatpak-runner com.qq.QQ") have
// arguments but no path, and must be executed verbatim.
static bool execIsRunnerStyle(const QString &exec)
{
    QStringList parts = exec.split(QLatin1Char(' '), QString::SkipEmptyParts);
    bool hasPath = false;
    int argc = 0;
    for (const QString &p : parts) {
        if (p.startsWith(QLatin1Char('%')))
            continue;   // desktop field codes
        if (p.startsWith(QLatin1Char('/')))
            hasPath = true;
        argc++;
    }
    return !hasPath && argc > 1;
}

static QString extractBinary(const QString &exec)
{
    QStringList parts = exec.split(QLatin1Char(' '), QString::SkipEmptyParts);
    QString binary = parts.value(0);
    for (int i = parts.count() - 1; i > 0; --i) {
        if (parts.at(i).startsWith(QLatin1Char('/'))) {
            binary = parts.at(i);
            break;
        }
    }
    return binary;
}

// System desktops only. User-local ones (~/.local/share/applications)
// include Android App Support / flatpak autogen launchers (e.g. QQ) whose
// rendering goes through the Android container's SurfaceFlinger — imira
// cannot host those surfaces, so skip the whole directory.
static void scanAvailableApps()
{
    g_available.clear();
    const QStringList dirs = {
        QStringLiteral("/usr/share/applications"),
    };
    for (const QString &dn : dirs) {
        QDir dir(dn);
        if (!dir.exists())
            continue;
        const QStringList files = dir.entryList(
            QStringList() << QStringLiteral("*.desktop"), QDir::Files);
        for (const QString &fn : files) {
            if (fn == QStringLiteral("harbour-sailplay.desktop"))
                continue; // The tablet manager is not a projection app.
            QString name, exec, icon;
            bool hidden = false;
            if (!parseDesktopFile(dir.filePath(fn), &name, &exec, &hidden,
                                  &icon))
                continue;
            if (hidden || name.isEmpty())
                continue;
            // Android App Support applications are rendered by the container's
            // SurfaceFlinger through Jolla's private alien_surface protocol.
            // imira cannot host those surfaces yet, so do not offer launchers
            // that would only open on the phone or interrupt projection.
            if (exec.startsWith(QStringLiteral("apkd-launcher "))
                    || exec == QLatin1String("apkd-launcher"))
                continue;
            AvailableApp a;
            a.id = fn.left(fn.size() - 8);
            // The phone-side configurator is not a projected app. Listing it
            // here would let users recursively launch Sailife on the car UI.
            if (a.id == QLatin1String("harbour-sailife"))
                continue;
            a.name = name;
            a.exec = execIsRunnerStyle(exec) ? exec : extractBinary(exec);
            a.icon = resolveIcon(icon);
            int found = -1;
            for (int i = 0; i < g_available.size(); ++i) {
                if (g_available[i].id == a.id) {
                    found = i;
                    break;
                }
            }
            if (found >= 0)
                g_available[found] = a;
            else
                g_available.append(a);
        }
    }
    std::sort(g_available.begin(), g_available.end(),
              [](const AvailableApp &a, const AvailableApp &b) {
                  return a.name.compare(b.name, Qt::CaseInsensitive) < 0;
              });
    fprintf(stderr, "carui: %d installed apps\n", g_available.size());
}

static const AvailableApp *findAvailable(const QString &id)
{
    for (const AvailableApp &a : g_available)
        if (a.id == id)
            return &a;
    return nullptr;
}

static QVector<AppInfo> readApps()
{
    QVector<AppInfo> apps;
    QString path = userConfigPath();
    QFile f(QFile::exists(path) ? path : QString::fromLatin1(kSystemConfig));
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
        return apps;
    while (!f.atEnd()) {
        QString line = QString::fromUtf8(f.readLine()).trimmed();
        if (line.isEmpty() || line.startsWith(QLatin1Char('#')))
            continue;
        // appId = everything after the FIRST colon; a missing trailing
        // newline on the last line once glued two lines together here
        int colon = line.indexOf(QLatin1Char(':'));
        if (colon <= 0)
            continue;
        QString category = line.left(colon).trimmed();
        QString appId = line.mid(colon + 1).trimmed();
        const AvailableApp *a = findAvailable(appId);
        if (!a || a->exec.isEmpty())
            continue;
        AppInfo ai;
        ai.category = category;
        ai.appId = appId;
        ai.name = a->name;
        ai.exec = a->exec;
        ai.icon = a->icon;
        apps.append(ai);
    }
    return apps;
}

static QString appKey(const QString &appId)
{
    return QString::fromLatin1(appId.toUtf8().toBase64());
}

static qint64 launchApp(const QString &appId, const QString &exec)
{
    QString cmd = QStringLiteral(
        "QT_QPA_PLATFORM=wayland WAYLAND_DISPLAY=imira-comp-0 "
        "QT_IM_MODULE=none "
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/"
        "user_bus_socket ");
    cmd += QStringLiteral("CARLIFE_APP_KEY=") + appKey(appId)
           + QStringLiteral(" exec ") + exec;
    qint64 pid = 0;
    QProcess::startDetached(QStringLiteral("/bin/sh"),
                            QStringList() << QStringLiteral("-c") << cmd,
                            QString(), &pid);
    return pid;
}

static QVector<AppInfo> g_apps;

// CarPlay-like shell state: dockApps = configured apps ordered by launch
// recency (most recent first); the home grid hides under the app window,
// so carui tracks which app is on screen and every still-running hidden app;
// dock taps switch between them without creating duplicate processes.
static QStringList g_recent;

static void loadRecent()
{
    g_recent.clear();
    QFile f(recentPath());
    if (f.open(QIODevice::ReadOnly | QIODevice::Text)) {
        while (!f.atEnd()) {
            const QString id = QString::fromUtf8(f.readLine()).trimmed();
            if (!id.isEmpty())
                g_recent.append(id);
        }
    }
}

static void saveRecent()
{
    QDir().mkpath(QDir::home().filePath(QStringLiteral(".config/carlife")));
    QFile f(recentPath());
    if (!f.open(QIODevice::WriteOnly | QIODevice::Text | QIODevice::Truncate))
        return;
    for (const QString &id : g_recent)
        f.write(id.toUtf8() + QByteArray("\n"));
}

static void moveToFront(const QString &appId)
{
    g_recent.removeAll(appId);
    g_recent.prepend(appId);
    // keep the file bounded: the dock shows the head of the list anyway
    while (g_recent.size() > 32)
        g_recent.removeLast();
    saveRecent();
}

// The compositor is the unmodified harbour-imira one: head-unit taps arrive
// as a REAL input-device mouse (uinput) and hit the Qt Quick scene, so
// carui must handle its own clicks with a MouseArea in QML. This controller
// is the bridge from QML to the launcher logic and the settings editor.
class CarUiController : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QVariantList tiles READ tiles NOTIFY tilesChanged)
    Q_PROPERTY(QVariantList rows READ rows NOTIFY rowsChanged)
    Q_PROPERTY(QStringList selectedApps READ selectedApps NOTIFY rowsChanged)
    Q_PROPERTY(QVariantList dockApps READ dockApps NOTIFY dockChanged)
    Q_PROPERTY(QString currentApp READ currentApp NOTIFY currentAppChanged)
    Q_PROPERTY(bool serviceRunning READ serviceRunning NOTIFY serviceRunningChanged)
    Q_PROPERTY(QVariantMap status READ status NOTIFY statusChanged)

public:
    explicit CarUiController(QObject *parent = nullptr) : QObject(parent)
    {
        QTimer *timer = new QTimer(this);
        connect(timer, &QTimer::timeout, this, [this]() {
            const QDateTime stamp = QFileInfo(userConfigPath()).lastModified();
            if (stamp != m_configStamp)
                reloadConfig();
            updateServiceState();
        });
        timer->start(1000);
        updateServiceState();
        QTimer *statusTimer = new QTimer(this);
        connect(statusTimer, &QTimer::timeout, this, &CarUiController::updateStatus);
        statusTimer->start(5000);
        updateStatus();
    }

    // one tile per config row (a category may appear several times)
    QVariantList tiles() const
    {
        QVariantList l;
        for (const AppInfo &a : g_apps) {
            QVariantMap m;
            m.insert(QStringLiteral("category"), a.category);
            m.insert(QStringLiteral("name"), a.name);
            m.insert(QStringLiteral("icon"), a.icon);
            l.append(m);
        }
        return l;
    }

    // dock: configured apps, most recently used first
    QVariantList dockApps() const
    {
        QVariantList l;
        for (const QString &id : g_recent) {
            const AvailableApp *a = findAvailable(id);
            if (!a)
                continue;
            QVariantMap m;
            m.insert(QStringLiteral("appId"), id);
            m.insert(QStringLiteral("name"), a->name);
            m.insert(QStringLiteral("icon"), a->icon);
            l.append(m);
        }
        return l;
    }

    // current editor state: [{category, appId, appName}, …]
    QVariantList rows() const { return m_rows; }
    QStringList selectedApps() const
    {
        QStringList ids;
        for (const QVariant &v : m_rows) {
            const QString id = v.toMap().value(QStringLiteral("appId")).toString();
            if (!id.isEmpty() && !ids.contains(id))
                ids.append(id);
        }
        return ids;
    }

    // appId of the app currently on screen ("" = home grid visible)
    QString currentApp() const { return m_currentApp; }
    bool serviceRunning() const { return m_serviceRunning; }
    QVariantMap status() const { return m_status; }

    Q_INVOKABLE void returnToCar()
    {
        // Never block the GUI when no media session owns the command pipe.
        int fd = ::open("/tmp/sailplay-ui-command", O_WRONLY | O_NONBLOCK | O_NOFOLLOW);
        if (fd < 0) {
            fprintf(stderr, "carui: return-to-car pipe open failed errno=%d\n", errno);
            return;
        }
        const char command[] = "return-car\n";
        const ssize_t written = ::write(fd, command, sizeof(command) - 1);
        if (written != sizeof(command) - 1)
            fprintf(stderr, "carui: return-to-car pipe write failed errno=%d\n", errno);
        else
            fprintf(stderr, "carui: return-to-car command queued\n");
        ::close(fd);
    }

    Q_INVOKABLE void setServiceRunning(bool running)
    {
        QDBusMessage call = QDBusMessage::createMethodCall(
            QStringLiteral("org.freedesktop.systemd1"),
            QStringLiteral("/org/freedesktop/systemd1"),
            QStringLiteral("org.freedesktop.systemd1.Manager"),
            running ? QStringLiteral("StartUnit") : QStringLiteral("StopUnit"));
        call << QStringLiteral("sailplay.service") << QStringLiteral("replace");
        QDBusConnection::systemBus().asyncCall(call);
        QTimer::singleShot(500, this, [this]() { updateServiceState(); });
    }

    Q_INVOKABLE void reloadConfig()
    {
        scanAvailableApps();
        g_apps = readApps();
        // recency entries for apps that no longer resolve are dead weight
        QStringList valid;
        for (const QString &id : g_recent) {
            if (findAvailable(id) && !valid.contains(id))
                valid.append(id);
        }
        for (const AppInfo &a : g_apps) {
            if (!valid.contains(a.appId))
                valid.append(a.appId);
        }
        g_recent = valid;
        m_rows.clear();
        for (const AppInfo &a : g_apps) {
            QVariantMap m;
            m.insert(QStringLiteral("category"), a.category);
            m.insert(QStringLiteral("appId"), a.appId);
            m.insert(QStringLiteral("appName"), a.name);
            m_rows.append(m);
        }
        emit tilesChanged();
        emit rowsChanged();
        m_configStamp = QFileInfo(userConfigPath()).lastModified();
        emit dockChanged();
        fprintf(stderr, "carui: %d apps configured\n", g_apps.size());
    }

    Q_INVOKABLE QVariantList availableApps() const
    {
        QVariantList l;
        for (const AvailableApp &a : g_available) {
            QVariantMap m;
            m.insert(QStringLiteral("id"), a.id);
            m.insert(QStringLiteral("name"), a.name);
            m.insert(QStringLiteral("icon"), a.icon);
            l.append(m);
        }
        return l;
    }

    Q_INVOKABLE void addMapping(const QString &category, const QString &appId)
    {
        for (const QVariant &v : m_rows) {
            QVariantMap m = v.toMap();
            if (m.value("category").toString() == category
                && m.value("appId").toString() == appId)
                return;
        }
        QVariantMap m;
        m.insert(QStringLiteral("category"), category);
        m.insert(QStringLiteral("appId"), appId);
        const AvailableApp *a = findAvailable(appId);
        m.insert(QStringLiteral("appName"),
                 a ? a->name : appId);
        m_rows.append(m);
        emit rowsChanged();
    }

    Q_INVOKABLE void removeMapping(int index)
    {
        if (index < 0 || index >= m_rows.size())
            return;
        m_rows.removeAt(index);
        emit rowsChanged();
    }

    Q_INVOKABLE bool toggleApp(const QString &appId)
    {
        bool removed = false;
        for (int i = m_rows.size() - 1; i >= 0; --i) {
            if (m_rows.at(i).toMap().value(QStringLiteral("appId")).toString()
                    == appId) {
                m_rows.removeAt(i);
                removed = true;
            }
        }
        if (!removed) {
            const AvailableApp *a = findAvailable(appId);
            if (!a)
                return false;
            QVariantMap m;
            m.insert(QStringLiteral("category"), QStringLiteral("其他"));
            m.insert(QStringLiteral("appId"), appId);
            m.insert(QStringLiteral("appName"), a->name);
            m_rows.append(m);
        }
        emit rowsChanged();
        return saveConfig();
    }

    Q_INVOKABLE bool saveConfig()
    {
        QFile f(userConfigPath());
        QDir().mkpath(QDir::home().filePath(QStringLiteral(".config/carlife")));
        if (!f.open(QIODevice::WriteOnly | QIODevice::Text | QIODevice::Truncate))
            return false;
        for (const QVariant &v : m_rows) {
            QVariantMap m = v.toMap();
            f.write(m.value("category").toString().toUtf8());
            f.write(":");
            f.write(m.value("appId").toString().toUtf8());
            f.write("\n");
        }
        f.close();
        if (f.error() != QFile::NoError)
            return false;
        g_apps = readApps();
        m_configStamp = QFileInfo(userConfigPath()).lastModified();
        emit tilesChanged();
        emit dockChanged();
        fprintf(stderr, "carui: config saved, %d apps\n", g_apps.size());
        return true;
    }

    Q_INVOKABLE void tileClicked(int index)
    {
        if (index < 0 || index >= g_apps.size())
            return;
        const AppInfo &a = g_apps[index];
        activate(a.appId, a.exec, a.name);
    }

    Q_INVOKABLE void dockClicked(const QString &appId)
    {
        const AvailableApp *a = findAvailable(appId);
        if (!a)
            return;
        activate(appId, a->exec, a->name);
    }

    Q_INVOKABLE void homeClicked()
    {
        if (m_currentApp.isEmpty())
            return;
        const QString appId = m_currentApp;
        hideCurrent();
        fprintf(stderr, "carui: home (hid %s)\n",
                appId.toUtf8().constData());
        emit currentAppChanged();
    }

signals:
    void tilesChanged();
    void rowsChanged();
    void dockChanged();
    void currentAppChanged();
    void serviceRunningChanged();
    void statusChanged();

private:
    QVariantMap m_status;
    void setStatus(const QString &key, const QVariant &value)
    {
        if (m_status.value(key) == value && m_status.contains(key)) return;
        m_status.insert(key, value);
        emit statusChanged();
    }
    void query(const QString &service, const QString &path, const QString &iface,
               const QString &method, const std::function<void(const QDBusMessage &)> &done,
               const QList<QVariant> &args = {})
    {
        QDBusMessage message = QDBusMessage::createMethodCall(service, path, iface, method);
        message.setArguments(args);
        auto *watcher = new QDBusPendingCallWatcher(QDBusConnection::systemBus().asyncCall(message, 3000), this);
        connect(watcher, &QDBusPendingCallWatcher::finished, this, [watcher, done]() {
            QDBusMessage reply = watcher->reply();
            if (reply.type() != QDBusMessage::ErrorMessage) done(reply);
            watcher->deleteLater();
        });
    }
    void updateStatus()
    {
        // Statefs is Sailfish's status provider; missing values stay unknown.
        QFile battery(QStringLiteral("/run/state/namespaces/Battery/ChargePercentage"));
        if (battery.open(QIODevice::ReadOnly)) {
            bool ok = false;
            int level = battery.readAll().trimmed().toInt(&ok);
            if (ok) setStatus("battery", qBound(0, level, 100));
        }
        QFile charging(QStringLiteral("/run/state/namespaces/Battery/IsCharging"));
        if (charging.open(QIODevice::ReadOnly)) setStatus("charging", charging.readAll().trimmed() == "1");
        query("org.freedesktop.UPower", "/org/freedesktop/UPower/devices/DisplayDevice",
              "org.freedesktop.DBus.Properties", "GetAll", [this](const QDBusMessage &r) {
            if (r.arguments().isEmpty()) return;
            QVariantMap p = qdbus_cast<QVariantMap>(r.arguments().first());
            if (p.value("IsPresent").toBool()) {
                setStatus("battery", qBound(0, qRound(p.value("Percentage").toDouble()), 100));
                setStatus("charging", p.value("State").toInt() == 1);
            }
        }, {QStringLiteral("org.freedesktop.UPower.Device")});
        query("net.connman", "/", "net.connman.Manager", "GetServices", [this](const QDBusMessage &r) {
            if (r.arguments().isEmpty()) return;
            const QDBusArgument a = r.arguments().first().value<QDBusArgument>();
            bool connected = false;
            int strength = 0;
            a.beginArray();
            while (!a.atEnd()) {
                QDBusObjectPath path; QVariantMap p;
                a.beginStructure(); a >> path >> p; a.endStructure();
                QString state = p.value("State").toString();
                if (p.value("Type") == "wifi" && (state == "ready" || state == "online")) {
                    connected = true; strength = p.value("Strength").toInt();
                }
            }
            a.endArray();
            setStatus("wifiConnected", connected);
            setStatus("wifiStrength", strength);
        });
        query("org.ofono", "/", "org.ofono.Manager", "GetModems", [this](const QDBusMessage &r) {
            if (r.arguments().isEmpty()) return;
            const QDBusArgument a = r.arguments().first().value<QDBusArgument>();
            QString modem;
            a.beginArray();
            while (!a.atEnd()) {
                QDBusObjectPath path; QVariantMap p;
                a.beginStructure(); a >> path >> p; a.endStructure();
                if (p.value("Online").toBool()) modem = path.path();
            }
            a.endArray();
            if (modem.isEmpty()) { setStatus("mobileStrength", -1); setStatus("mobileType", ""); return; }
            query("org.ofono", modem, "org.ofono.NetworkRegistration", "GetProperties", [this](const QDBusMessage &reply) {
                if (reply.arguments().isEmpty()) return;
                QVariantMap p = qdbus_cast<QVariantMap>(reply.arguments().first());
                bool registered = p.value("Status") == "registered" || p.value("Status") == "roaming";
                setStatus("mobileStrength", registered ? p.value("Strength").toInt() : -1);
                QString tech = p.value("Technology").toString();
                setStatus("mobileType", tech == "lte" ? "4G" : tech == "nr" ? "5G" : tech == "umts" || tech == "hspa" || tech == "hspap" ? "3G" : registered ? "2G" : "");
            });
        });
    }
    QVariantList m_rows;
    QString m_currentApp;
    QSet<QString> m_hiddenApps;
    QString m_lastHiddenApp;
    QDateTime m_configStamp;
    bool m_serviceRunning = false;

    void updateServiceState()
    {
        QDBusMessage call = QDBusMessage::createMethodCall(
            QStringLiteral("org.freedesktop.systemd1"),
            QStringLiteral("/org/freedesktop/systemd1/unit/sailplay_2eservice"),
            QStringLiteral("org.freedesktop.DBus.Properties"),
            QStringLiteral("Get"));
        call << QStringLiteral("org.freedesktop.systemd1.Unit")
             << QStringLiteral("ActiveState");
        const QDBusMessage reply = QDBusConnection::systemBus().call(call);
        bool running = false;
        if (!reply.arguments().isEmpty()) {
            const QDBusVariant value = qvariant_cast<QDBusVariant>(
                reply.arguments().first());
            const QString state = value.variant().toString();
            running = state == QLatin1String("active")
                   || state == QLatin1String("activating");
        }
        if (running != m_serviceRunning) {
            m_serviceRunning = running;
            emit serviceRunningChanged();
        }
    }
    // CarPlay semantics: the tapped app replaces whatever is on screen; a
    // hidden app comes back instead of being launched twice (native apps
    // launched as bare binaries have no single-instance guard).
    void activate(const QString &appId, const QString &exec,
                  const QString &name)
    {
        if (appId == m_currentApp)
            return;   // already on screen
        if (m_hiddenApps.contains(appId)) {
            const bool restoreLast = m_currentApp.isEmpty()
                                     && appId == m_lastHiddenApp;
            // Switching between two already-running apps must hide the
            // current one before restoring the requested one. Otherwise the
            // compositor has two visible/input-capable content surfaces.
            if (!m_currentApp.isEmpty())
                hideCurrent();
            writeCmd(restoreLast ? QStringLiteral("S")
                                 : QStringLiteral("S ") + appKey(appId));
            m_currentApp = appId;
            m_hiddenApps.remove(appId);
            fprintf(stderr, "carui: showing %s\n",
                    name.toUtf8().constData());
            emit currentAppChanged();
            return;
        }
        fprintf(stderr, "carui: launching %s\n", name.toUtf8().constData());
        launchApp(appId, exec);
        moveToFront(appId);
        if (!m_currentApp.isEmpty())
            hideCurrent();   // the new app replaces the one on screen
        m_currentApp = appId;
        emit dockChanged();
        emit currentAppChanged();
    }

    void writeCmd(const QString &cmd)
    {
        FILE *tf = fopen("/tmp/imira-touch", "a");
        if (tf) {
            fprintf(tf, "%s\n", cmd.toUtf8().constData());
            fclose(tf);
        }
    }

    // H <name>: hide the app on screen (named so the compositor can tell
    // stacked hidden apps apart)
    void hideCurrent()
    {
        writeCmd(QStringLiteral("H"));
        m_hiddenApps.insert(m_currentApp);
        m_lastHiddenApp = m_currentApp;
        m_currentApp.clear();
    }
};

static void inheritSystemLocale()
{
    if (!qgetenv("LANG").isEmpty())
        return;
    QFile f(QStringLiteral("/etc/locale.conf"));
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
        return;
    while (!f.atEnd()) {
        const QByteArray line = f.readLine().trimmed();
        if (line.startsWith("LANG=")) {
            const QByteArray locale = line.mid(5);
            qputenv("LANG", locale);
            qputenv("LC_MESSAGES", locale);
            break;
        }
    }
}

Q_DECL_EXPORT int main(int argc, char **argv)
{
    ::signal(SIGPIPE, SIG_IGN);
    inheritSystemLocale();
    QGuiApplication app(argc, argv);
    const bool mobileSettings = argc > 1
        && QString::fromLocal8Bit(argv[1]).endsWith(
            QStringLiteral("mobile-settings.qml"));
    app.setApplicationName(mobileSettings ? QStringLiteral("harbour-sailplay")
                                          : QStringLiteral("carlife-ui"));
    QQmlApplicationEngine engine;

    CarUiController controller;
    engine.rootContext()->setContextProperty("carController", &controller);
    loadRecent();
    controller.reloadConfig();

    const char *qml = argc > 1 ? argv[1] : "/opt/sailplay/carui/main.qml";
    if (mobileSettings) {
        QQuickView *view = SailfishApp::createView();
        view->rootContext()->setContextProperty("carController", &controller);
        view->setSource(QUrl::fromLocalFile(QString::fromLocal8Bit(qml)));
        if (view->status() == QQuickView::Error) {
            for (const auto &e : view->errors())
                fprintf(stderr, "QML error: %s\n",
                        e.toString().toUtf8().constData());
            delete view;
            return 1;
        }
        view->show();
        fprintf(stderr, "carui: showing mobile settings %s\n", qml);
        const int result = app.exec();
        delete view;
        return result;
    }

    QQmlComponent comp(&engine, QUrl::fromLocalFile(qml));
    if (comp.isError()) {
        for (const auto &e : comp.errors())
            fprintf(stderr, "QML error: %s\n", e.toString().toUtf8().constData());
        return 1;
    }
    QObject *rootObj = comp.create();
    if (!rootObj) {
        fprintf(stderr, "carui: component create failed\n");
        return 1;
    }
    QQuickWindow *win = qobject_cast<QQuickWindow *>(rootObj);
    if (!win && !mobileSettings) {
        fprintf(stderr, "carui: no window\n");
        return 1;
    }

    fprintf(stderr, "carui: loaded %s\n", qml);
    return app.exec();
}

#include "main.moc"
