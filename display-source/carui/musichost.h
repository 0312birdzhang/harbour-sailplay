#ifndef SAILPLAY_MUSIC_HOST_H
#define SAILPLAY_MUSIC_HOST_H

#include "sailplayapplication.h"
#include "sailplaysession.h"

class SailplayMusicHost : public QObject
{
    Q_OBJECT
public:
    explicit SailplayMusicHost(QObject *parent = nullptr);
    void open(const SailplayApplication &application);
    void setActive(bool active);
    void close();

signals:
    void errorOccurred(const QString &message);

private:
    SailplaySession m_session;
    QString m_service;
    QString m_path;
    bool m_active = false;
    bool m_opening = false;
};

#endif
