#include "sailplayrenderer.h"

#include <QSocketNotifier>
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>

SailplayRenderer::SailplayRenderer(QObject *parent) : SailplaySession(parent)
{
    connect(this, &SailplaySession::readyChanged, this, [this](bool ready) {
        if (ready) setActive(m_active);
    });
}

bool SailplayRenderer::start()
{
    if (m_input || m_finished || qgetenv("WAYLAND_DISPLAY") != QByteArray("imira-comp-0")
        || qgetenv("CARLIFE_APP_KEY").isEmpty()) return false;
    const QString service = QString::fromUtf8(qgetenv("SAILPLAY_RENDERER_SERVICE"));
    const QString path = QString::fromUtf8(qgetenv("SAILPLAY_RENDERER_PATH"));
    if (service.isEmpty() || path.isEmpty()) return false;
    const int flags = fcntl(STDIN_FILENO, F_GETFL);
    if (flags < 0 || fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK) < 0) return false;
    m_input = new QSocketNotifier(STDIN_FILENO, QSocketNotifier::Read, this);
    connect(m_input, &QSocketNotifier::activated, this, [this](int) { readCommands(); });
    open(service, path, QStringLiteral("car"));
    return true;
}

void SailplayRenderer::readCommands()
{
    char bytes[128];
    const ssize_t count = read(STDIN_FILENO, bytes, sizeof(bytes));
    if (count < 0 && (errno == EAGAIN || errno == EINTR)) return;
    if (count <= 0) { finish(); return; }
    m_commands.append(bytes, int(count));
    if (m_commands.size() > 256) { finish(); return; }
    int end;
    while ((end = m_commands.indexOf('\n')) >= 0) {
        const QByteArray command = m_commands.left(end);
        m_commands.remove(0, end + 1);
        if (command != "active" && command != "inactive") { finish(); return; }
        const bool active = command == "active";
        if (active == m_active) continue;
        m_active = active;
        setActive(active);
        emit activeChanged();
    }
}

void SailplayRenderer::finish()
{
    if (m_finished) return;
    m_finished = true;
    if (m_input) m_input->setEnabled(false);
    close();
    emit closed();
}
