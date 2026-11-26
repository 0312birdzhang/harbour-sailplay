#include "../display-source/carui/inputdismissal.h"
#include <QQmlComponent>
#include <QQmlEngine>
#include <QTouchDevice>
#include <cstdio>
#include <memory>

#define CHECK(condition) do { if (!(condition)) { std::fprintf(stderr, "INPUT_DISMISSAL_FAIL line=%d %s\n", __LINE__, #condition); return 1; } } while (false)

static void click(QQuickWindow *window, const QPointF &point)
{
    for (const auto type : {QEvent::MouseButtonPress, QEvent::MouseButtonRelease}) {
        QMouseEvent event(type, point, Qt::LeftButton,
                          type == QEvent::MouseButtonPress ? Qt::LeftButton : Qt::NoButton,
                          Qt::NoModifier);
        QCoreApplication::sendEvent(window, &event);
    }
}

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    SailplayInputDismissal dismissal;
    app.installEventFilter(&dismissal);
    QQmlEngine engine;
    QQmlComponent component(&engine);
    component.setData(R"(
        import QtQuick 2.0
        import QtQuick.Window 2.0
        Window {
            id: testWindow
            width: 600; height: 400
            property int clicked: 0
            TextInput { objectName: "first"; x: 30; y: 30; width: 200; height: 60; text: "sample" }
            TextInput { objectName: "second"; x: 30; y: 150; width: 200; height: 60 }
            MouseArea { x: 350; y: 30; width: 100; height: 60; onClicked: testWindow.clicked++ }
        }
    )", QUrl());
    std::unique_ptr<QObject> object(component.create());
    CHECK(object);
    auto *window = qobject_cast<QQuickWindow *>(object.get());
    auto *first = object->findChild<QQuickItem *>("first");
    auto *second = object->findChild<QQuickItem *>("second");
    CHECK(window && first && second);
    QCoreApplication::processEvents();
    first->forceActiveFocus();
    CHECK(first->hasActiveFocus());
    click(window, QPointF(60, 50));
    CHECK(first->hasActiveFocus());
    click(window, QPointF(550, 300));
    CHECK(!first->hasActiveFocus());
    first->forceActiveFocus();
    click(window, QPointF(380, 50));
    CHECK(!first->hasActiveFocus() && window->property("clicked").toInt() == 1);
    first->forceActiveFocus();
    click(window, QPointF(60, 170));
    CHECK(second->hasActiveFocus());

    // Scene coordinates must account for transformed editors.
    first->setScale(1.5);
    first->forceActiveFocus();
    click(window, first->mapToScene(QPointF(190, 30)));
    CHECK(first->hasActiveFocus());

    QTouchDevice device;
    device.setType(QTouchDevice::TouchScreen);
    QTouchEvent::TouchPoint point(0);
    point.setState(Qt::TouchPointPressed);
    point.setPos(QPointF(550, 300));
    QTouchEvent touch(QEvent::TouchBegin, &device, Qt::NoModifier, Qt::TouchPointPressed, {point});
    QCoreApplication::sendEvent(window, &touch);
    CHECK(!first->hasActiveFocus());
    std::puts("INPUT_DISMISSAL_PASS inside outside button-delivery second-editor scale touch");
    return 0;
}
