#include "sailplayapplication.h"

#include <QFile>
#include <QFileInfo>
#include <QMap>
#include <QRegExp>
#include <QDir>
#include <QSettings>

SailplayApplication SailplayApplication::fromDesktopFile(const QString &filename)
{
    SailplayApplication result;
    QFile source(filename);
    if (!filename.endsWith(QStringLiteral(".desktop")) || !source.open(QIODevice::ReadOnly))
        return result;
    QMap<QString, QString> values;
    bool desktopEntry = false;
    bool duplicate = false;
    while (!source.atEnd()) {
        const QString line = QString::fromUtf8(source.readLine()).trimmed();
        if (line.startsWith(QLatin1Char('['))) {
            desktopEntry = line == QStringLiteral("[Desktop Entry]");
            continue;
        }
        if (!desktopEntry || line.startsWith(QLatin1Char('#'))) continue;
        const int equals = line.indexOf(QLatin1Char('='));
        if (equals < 0) continue;
        const QString key = line.left(equals).trimmed();
        duplicate = duplicate || values.contains(key);
        values.insert(key, line.mid(equals + 1).trimmed());
    }
    result.declared = values.contains(QStringLiteral("X-Sailplay-Service"))
        || values.contains(QStringLiteral("X-Sailplay-ApiVersion"));
    if (!result.declared || duplicate
        || values.value(QStringLiteral("Type")) != QStringLiteral("Application")
        || values.value(QStringLiteral("X-Sailplay-ApiVersion")) != QStringLiteral("1"))
        return result;
    result.desktopId = QFileInfo(filename).completeBaseName();
    result.applicationId = values.value(QStringLiteral("X-Sailplay-ApplicationId"), result.desktopId);
    result.service = values.value(QStringLiteral("X-Sailplay-Service"));
    result.path = values.value(QStringLiteral("X-Sailplay-ObjectPath"), QStringLiteral("/org/sailplay/v1/App"));
    result.presentation = values.value(QStringLiteral("X-Sailplay-Presentation"), QStringLiteral("template"));
    result.capabilities = values.value(QStringLiteral("X-Sailplay-Capabilities"))
        .split(QLatin1Char(';'), QString::SkipEmptyParts);
    const QRegExp servicePattern(QStringLiteral("[A-Za-z_-][A-Za-z0-9_-]*(\\.[A-Za-z_-][A-Za-z0-9_-]*)+"));
    const QRegExp pathPattern(QStringLiteral("(/[A-Za-z0-9_]+)+"));
    const QRegExp capabilityPattern(QStringLiteral("[a-z][a-z0-9.-]*"));
    if (result.applicationId.isEmpty() || result.service.size() > 255
        || result.applicationId.contains(QChar::Null) || result.applicationId.contains(QLatin1Char('/'))
        || result.applicationId.contains(QLatin1Char('\\')) || result.applicationId == QStringLiteral(".")
        || result.applicationId == QStringLiteral("..")
        || !servicePattern.exactMatch(result.service) || !pathPattern.exactMatch(result.path)
        || !result.path.split(QLatin1Char('/')).contains(QStringLiteral("v1"))
        || (result.presentation != QStringLiteral("template") && result.presentation != QStringLiteral("renderer")))
        return result;
    for (const QString &capability : result.capabilities) {
        if (!capabilityPattern.exactMatch(capability)) return result;
    }
    if (result.presentation == QStringLiteral("renderer")) {
        result.rendererDesktopId = values.value(QStringLiteral("X-Sailplay-RendererDesktop"));
        const QRegExp desktopPattern(QStringLiteral("[A-Za-z0-9_-][A-Za-z0-9_.-]*"));
        if (!desktopPattern.exactMatch(result.rendererDesktopId)) return result;
        const QString rendererFile = QFileInfo(filename).dir().filePath(result.rendererDesktopId + QStringLiteral(".desktop"));
        QSettings renderer(rendererFile, QSettings::IniFormat);
        const QString organization = renderer.value(QStringLiteral("X-Sailjail/OrganizationName")).toString();
        const QString application = renderer.value(QStringLiteral("X-Sailjail/ApplicationName")).toString();
        result.rendererExecutable = renderer.value(QStringLiteral("Desktop Entry/Exec")).toString();
        const QRegExp executablePattern(QStringLiteral("/usr/bin/[A-Za-z0-9_.-]+"));
        if (renderer.value(QStringLiteral("Desktop Entry/Type")).toString() != QStringLiteral("Application")
            || !servicePattern.exactMatch(organization + QLatin1Char('.') + application)
            || renderer.value(QStringLiteral("X-Sailjail/Sandboxing")).toString() == QStringLiteral("Disabled")
            || !executablePattern.exactMatch(result.rendererExecutable)) return result;
    }
    result.valid = true;
    return result;
}
