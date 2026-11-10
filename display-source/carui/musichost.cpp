#include "musichost.h"

#include <QSignalBlocker>

SailplayMusicHost::SailplayMusicHost(QObject *parent)
    : QObject(parent), m_session(this)
{
    connect(&m_session, &SailplaySession::readyChanged, this, [this](bool ready) {
        if (ready) {
            m_opening = false;
            m_session.setActive(m_active);
        }
    });
    connect(&m_session, &SailplaySession::errorOccurred, this,
        [this](const QString &, const QString &message) {
            m_service.clear();
            m_path.clear();
            m_opening = false;
            emit errorOccurred(message);
        });
}

void SailplayMusicHost::open(const SailplayApplication &application)
{
    if (!application.mediaTemplate()) {
        close();
        return;
    }
    if (m_service == application.service && m_path == application.path && (m_session.ready() || m_opening)) return;
    close();
    m_service = application.service;
    m_path = application.path;
    m_opening = true;
    m_session.open(m_service, m_path, QStringLiteral("car"), QStringList() << QStringLiteral("media"));
}

void SailplayMusicHost::setActive(bool active)
{
    if (m_active == active) return;
    m_active = active;
    if (m_session.ready()) m_session.setActive(active);
}

void SailplayMusicHost::close()
{
    const QSignalBlocker blocker(&m_session);
    m_session.close();
    m_service.clear();
    m_path.clear();
    m_opening = false;
}
