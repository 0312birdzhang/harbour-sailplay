#include "navigationhost.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTimer>
#include <cstdio>
#include <unistd.h>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    if (app.arguments().size() != 3) return 2;
    const SailplayApplication declaration = SailplayApplication::fromDesktopFile(app.arguments().at(1));
    if (!declaration.navigationTemplate()) return 2;
    const QString runtime = app.arguments().at(2);
    const QString snapshot = QDir(runtime).filePath(QStringLiteral("sailplay-navigation/sailplay-sdk-%1.json").arg(getpid()));
    SailplayNavigationHost host(runtime);
    SailplaySession phone;
    bool requested = false;
    bool closingPhone = false;
    bool stopping = false;
    bool completed = false;
    QString failure;
    QString phase = QStringLiteral("connecting");
    auto fail = [&](const QString &message) {
        failure = message;
        app.quit();
    };
    QObject::connect(&phone, &SailplaySession::readyChanged, &app, [&](bool ready) {
        fprintf(stderr, "NAVIGATION_QT_PHONE ready=%d revision=%llu\n", ready, phone.revision());
        if (ready && !requested) {
            requested = true;
            phase = QStringLiteral("waiting for active guidance");
            phone.invoke(QStringLiteral("navigation.start"));
        }
    });
    QObject::connect(&phone, &SailplaySession::errorOccurred, &app,
        [&](const QString &, const QString &message) { fail(message); });
    QObject::connect(&phone, &SailplaySession::requestFinished, &app,
        [&](qulonglong request, qulonglong revision, const QVariantMap &, const QString &name, const QString &message) {
            fprintf(stderr, "NAVIGATION_QT_REQUEST id=%llu revision=%llu error=%s\n", request, revision, qPrintable(name));
            if (!closingPhone && !name.isEmpty()) fail(message);
        });
    QObject::connect(&host, &SailplayNavigationHost::changed, &app, [&]() {
        fprintf(stderr, "NAVIGATION_QT_HOST ready=%d state=%s error=%s\n", host.ready(),
                qPrintable(host.guidance().value(QStringLiteral("state")).toString()), qPrintable(host.error()));
        if (!host.error().isEmpty()) { fail(host.error()); return; }
        const QVariantMap guidance = host.guidance();
        if (host.ready() && guidance.value(QStringLiteral("state")) == QStringLiteral("active") && !closingPhone) {
            closingPhone = true;
            QFile file(snapshot);
            if (!file.open(QIODevice::ReadOnly)) { fail(QStringLiteral("guidance export is absent")); return; }
            const QJsonObject value = QJsonDocument::fromJson(file.readAll()).object();
            if (value.value(QStringLiteral("schema")).toInt() != 2
                || value.value(QStringLiteral("sequence")).toString().isEmpty()
                || !value.value(QStringLiteral("navigation")).toObject().value(QStringLiteral("remainingSeconds")).isString()
                || guidance.value(QStringLiteral("nextRoad")).toString() != QString::fromUtf8("下一条路")) {
                fail(QStringLiteral("guidance export or Unicode state is invalid"));
                return;
            }
            if (QFileInfo(file).permissions() & (QFile::ReadGroup | QFile::WriteGroup | QFile::ReadOther | QFile::WriteOther)) {
                fail(QStringLiteral("guidance export permissions are invalid"));
                return;
            }
            phone.close();
            host.setActive(false);
            phase = QStringLiteral("phone closed and car hidden");
            QTimer::singleShot(500, &app, [&]() {
                if (!host.ready() || host.guidance().value(QStringLiteral("state")) != QStringLiteral("active")) {
                    fail(QStringLiteral("closing a phone view or hiding a car view ended navigation"));
                    return;
                }
                stopping = true;
                phase = QStringLiteral("waiting for stopped guidance");
                host.setActive(true);
                host.stopNavigation();
            });
        }
        if (stopping && guidance.value(QStringLiteral("state")) == QStringLiteral("stopped")) {
            if (!guidance.value(QStringLiteral("nextRoad")).toString().isEmpty()
                || guidance.value(QStringLiteral("remainingDistanceMeters")).toDouble() != 0) {
                fail(QStringLiteral("stopped navigation retained guidance"));
                return;
            }
            completed = true;
            phase = QStringLiteral("stopped");
            app.quit();
        }
    });
    host.open(declaration, QStringLiteral("SDK navigation probe"));
    phone.open(declaration.service, declaration.path, QStringLiteral("phone"), {QStringLiteral("navigation")});
    QTimer::singleShot(10000, &app, &QCoreApplication::quit);
    app.exec();
    if (!completed && failure.isEmpty()) {
        failure = QStringLiteral("Timeout during %1. Host ready=%2, phone ready=%3, state=%4")
            .arg(phase).arg(host.ready()).arg(phone.ready())
            .arg(host.guidance().value(QStringLiteral("state")).toString());
    }
    phone.close();
    host.close();
    if (!completed || !failure.isEmpty() || QFile::exists(snapshot)) {
        fprintf(stderr, "NAVIGATION_QT_HOST_FAIL %s\n", qPrintable(failure));
        return 1;
    }
    printf("NAVIGATION_QT_HOST_PASS phone-close hidden-car explicit-stop Unicode private-export cleanup\n");
    return 0;
}
