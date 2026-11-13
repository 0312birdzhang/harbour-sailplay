#include "sailplayrenderer.h"

#include <QGuiApplication>
#include <QPainter>
#include <QQuickPaintedItem>
#include <QQuickWindow>
#include <QMouseEvent>
#include <cstdio>

class CounterItem : public QQuickPaintedItem
{
public:
    CounterItem(SailplayRenderer *session, QQuickItem *parent) : QQuickPaintedItem(parent), m_session(session)
    {
        setAcceptedMouseButtons(Qt::LeftButton);
        connect(session, &SailplaySession::stateChanged, this, [this]() { update(); });
    }

    void paint(QPainter *painter) override
    {
        painter->fillRect(boundingRect(), QColor("#142638"));
        painter->setPen(Qt::white);
        QFont font = painter->font();
        font.setPixelSize(40);
        painter->setFont(font);
        painter->drawText(boundingRect(), Qt::AlignCenter,
            QStringLiteral("Shared counter %1\nTap to increment").arg(m_session->state().value("value").toLongLong()));
    }

protected:
    void mousePressEvent(QMouseEvent *event) override
    {
        event->accept();
    }

    void mouseReleaseEvent(QMouseEvent *event) override
    {
        if (event->button() == Qt::LeftButton && m_session->ready())
            m_session->invoke(QStringLiteral("increment"), {{QStringLiteral("amount"), qint64(1)}});
        event->accept();
    }

private:
    SailplayRenderer *m_session;
};

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    SailplayRenderer session;
    QQuickWindow window;
    window.setTitle(QStringLiteral("Sailplay SDK renderer"));
    window.resize(1280, 720);
    CounterItem item(&session, window.contentItem());
    item.setSize(window.size());
    QObject::connect(&window, &QQuickWindow::widthChanged, &item, [&]() { item.setWidth(window.width()); });
    QObject::connect(&window, &QQuickWindow::heightChanged, &item, [&]() { item.setHeight(window.height()); });
    QObject::connect(&session, &SailplayRenderer::closed, &app, &QGuiApplication::quit);
    QObject::connect(&session, &SailplaySession::errorOccurred, &app,
        [](const QString &name, const QString &message) { fprintf(stderr, "%s %s\n", qPrintable(name), qPrintable(message)); });
    if (!session.start()) return 1;
    window.show();
    return app.exec();
}
