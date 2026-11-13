#ifndef SAILPLAY_APPLICATION_H
#define SAILPLAY_APPLICATION_H

#include <QString>
#include <QStringList>

struct SailplayApplication
{
    bool declared = false;
    bool valid = false;
    QString applicationId;
    QString service;
    QString path;
    QString presentation;
    QStringList capabilities;
    QString desktopId;
    QString rendererDesktopId;
    QString rendererExecutable;

    QString presentationId() const { return desktopId.isEmpty() ? applicationId : desktopId; }

    bool renderer() const
    {
        return valid && presentation == QStringLiteral("renderer") && !rendererExecutable.isEmpty();
    }

    bool navigationTemplate() const
    {
        return valid && presentation == QStringLiteral("template")
            && capabilities.contains(QStringLiteral("navigation"));
    }

    bool mediaTemplate() const
    {
        return valid && presentation == QStringLiteral("template")
            && capabilities.contains(QStringLiteral("media"));
    }

    bool contentTemplate() const
    {
        return valid && presentation == QStringLiteral("template")
            && capabilities.contains(QStringLiteral("content"));
    }

    static SailplayApplication fromDesktopFile(const QString &filename);
};

#endif
