import QtQuick 2.0

Canvas {
    property color ink: "white"
    property bool filled: false
    onInkChanged: requestPaint()
    onFilledChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        var context = getContext("2d")
        context.clearRect(0, 0, width, height)
        context.strokeStyle = ink
        context.fillStyle = ink
        context.lineWidth = Math.max(1.5, Math.min(width, height) * 0.07)
        context.lineJoin = "round"
        context.beginPath()
        for (var point = 0; point < 10; point++) {
            var angle = -Math.PI / 2 + point * Math.PI / 5
            var radius = Math.min(width, height) * (point % 2 ? 0.2 : 0.44)
            var x = width / 2 + Math.cos(angle) * radius
            var y = height / 2 + Math.sin(angle) * radius
            if (point === 0) context.moveTo(x, y)
            else context.lineTo(x, y)
        }
        context.closePath()
        if (filled) context.fill()
        context.stroke()
    }
}
