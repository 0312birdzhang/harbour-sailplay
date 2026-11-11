#include "mapcanvas.h"

#include <QPainter>

SailplayMapCanvas::SailplayMapCanvas(QQuickItem *parent) : QQuickPaintedItem(parent)
{
    setAntialiasing(false);
}

void SailplayMapCanvas::setProvider(QObject *provider)
{
    auto *host = qobject_cast<SailplayNavigationHost *>(provider);
    if (host == m_provider) return;
    if (m_provider) disconnect(m_provider, nullptr, this, nullptr);
    m_provider = host;
    if (m_provider) connect(m_provider, &SailplayNavigationHost::mapChanged, this, [this] { update(); });
    m_pressed = false;
    update();
    emit providerChanged();
}

QRectF SailplayMapCanvas::imageRect() const
{
    if (!m_provider || !m_provider->mapReady()) return QRectF();
    const QSizeF size = m_provider->mapImage().size();
    const qreal scale = qMin(width() / size.width(), height() / size.height());
    const QSizeF fitted = size * scale;
    return QRectF(QPointF((width() - fitted.width()) / 2, (height() - fitted.height()) / 2), fitted);
}

void SailplayMapCanvas::paint(QPainter *painter)
{
    if (m_provider) painter->drawImage(imageRect(), m_provider->mapImage());
}

void SailplayMapCanvas::touch(const QString &phase, double x, double y)
{
    const QRectF rect = imageRect();
    if (rect.isEmpty()) { m_pressed = false; return; }
    if (phase == QStringLiteral("press")) m_pressed = rect.contains(QPointF(x, y));
    if (!m_pressed) return;
    m_provider->mapTouch(phase, qBound(0.0, (x - rect.left()) / rect.width(), 1.0),
        qBound(0.0, (y - rect.top()) / rect.height(), 1.0));
    if (phase == QStringLiteral("release") || phase == QStringLiteral("cancel")) m_pressed = false;
}
