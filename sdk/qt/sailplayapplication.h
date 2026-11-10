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

    bool navigationTemplate() const
    {
        return valid && presentation == QStringLiteral("template")
            && capabilities.contains(QStringLiteral("navigation"));
    }

    static SailplayApplication fromDesktopFile(const QString &filename);
};

#endif
