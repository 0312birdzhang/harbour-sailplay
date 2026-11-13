#ifndef SAILPLAY_RENDERER_H
#define SAILPLAY_RENDERER_H

#include "sailplaysession.h"

class QSocketNotifier;

// A dedicated renderer owns one car session. The host controls its visibility
// and lifetime over stdin, which Sailjail passes to the application.
class SailplayRenderer : public SailplaySession
{
    Q_OBJECT
    Q_PROPERTY(bool active READ active NOTIFY activeChanged)
public:
    explicit SailplayRenderer(QObject *parent = nullptr);
    bool active() const { return m_active; }
    Q_INVOKABLE bool start();

signals:
    void activeChanged();
    void closed();

private:
    void readCommands();
    void finish();
    QSocketNotifier *m_input = nullptr;
    QByteArray m_commands;
    bool m_active = true;
    bool m_finished = false;
};

#endif
