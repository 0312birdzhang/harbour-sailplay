#ifndef SAILPLAY_INPUT_DISMISSAL_H
#define SAILPLAY_INPUT_DISMISSAL_H

#include <QEvent>
#include <QGuiApplication>
#include <QInputMethod>
#include <QMouseEvent>
#include <QObject>
#include <QQuickItem>
#include <QQuickWindow>
#include <QTouchEvent>

// Qt Quick buttons and empty space do not normally take text input focus.
// Blur before delivery so the clicked control still receives the same press,
// and another editor can take focus and open the input panel normally.
class SailplayInputDismissal : public QObject
{
public:
    using QObject::QObject;

protected:
    bool eventFilter(QObject *target, QEvent *event) override
    {
        QQuickWindow *window = qobject_cast<QQuickWindow *>(target);
        if (!window) return false;
        QPointF position;
        if (event->type() == QEvent::MouseButtonPress) {
            const auto *press = static_cast<QMouseEvent *>(event);
            if (press->button() != Qt::LeftButton) return false;
            position = press->localPos();
        } else if (event->type() == QEvent::TouchBegin) {
            const auto *touch = static_cast<QTouchEvent *>(event);
            if (touch->touchPoints().isEmpty()) return false;
            position = touch->touchPoints().first().pos();
        } else {
            return false;
        }

        QQuickItem *editor = window->activeFocusItem();
        if (editor && editor->flags().testFlag(QQuickItem::ItemAcceptsInputMethod)
                && !editor->contains(editor->mapFromScene(position))) {
            editor->setFocus(false, Qt::MouseFocusReason);
            window->contentItem()->forceActiveFocus(Qt::MouseFocusReason);
            QGuiApplication::inputMethod()->hide();
        }
        return false;
    }
};

#endif
