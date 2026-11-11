#ifndef SAILPLAY_MAP_CANVAS_H
#define SAILPLAY_MAP_CANVAS_H

#include "navigationhost.h"

#include <QPointer>
#include <QQuickPaintedItem>

class SailplayMapCanvas : public QQuickPaintedItem
{
    Q_OBJECT
    Q_PROPERTY(QObject *provider READ provider WRITE setProvider NOTIFY providerChanged)

public:
    explicit SailplayMapCanvas(QQuickItem *parent = nullptr);
    QObject *provider() const { return m_provider; }
    void setProvider(QObject *provider);
    void paint(QPainter *painter) override;
    Q_INVOKABLE void touch(const QString &phase, double x, double y);

signals:
    void providerChanged();

private:
    QRectF imageRect() const;
    QPointer<SailplayNavigationHost> m_provider;
    bool m_pressed = false;
};

#endif
