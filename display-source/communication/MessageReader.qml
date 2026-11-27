import QtQuick 2.0

Item {
    id: reader
    property var palette
    property var provider
    property real uiScale: 1
    signal reply()
    function buttonColor(pressed) {
        if (pressed) return reader.palette.ambience ? Qt.rgba(reader.palette.highlightColor.r, reader.palette.highlightColor.g, reader.palette.highlightColor.b, 0.35) : reader.palette.pressed
        return reader.palette.ambience ? Qt.rgba(reader.palette.highlightBackgroundColor.r, reader.palette.highlightBackgroundColor.g, reader.palette.highlightBackgroundColor.b, 0.55) : reader.palette.button
    }
    Row {
        id: header
        width: parent.width; height: 60 * reader.uiScale; spacing: 12 * reader.uiScale
        Rectangle {
            width: 100 * reader.uiScale; height: parent.height; radius: 14; color: reader.buttonColor(backTouch.pressed)
            Text { anchors.centerIn: parent; text: "‹"; color: backTouch.pressed ? reader.palette.highlightColor : reader.palette.text; font.pixelSize: 36 * reader.uiScale }
            MouseArea { id: backTouch; anchors.fill: parent; onClicked: reader.provider.back() }
        }
        Text {
            width: Math.max(0, parent.width - 260 * reader.uiScale); height: parent.height
            verticalAlignment: Text.AlignVCenter; font.pixelSize: 28 * reader.uiScale; color: reader.palette.highlightColor
            text: reader.provider.page.title || ""; elide: Text.ElideRight; textFormat: Text.PlainText
        }
        Rectangle {
            width: 136 * reader.uiScale; height: parent.height; radius: 14; color: reader.buttonColor(replyTouch.pressed)
            Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Reply"); color: replyTouch.pressed ? reader.palette.highlightColor : reader.palette.text; font.pixelSize: 26 * reader.uiScale }
            MouseArea { id: replyTouch; anchors.fill: parent; enabled: reader.provider.ready && !reader.provider.busy; onClicked: reader.reply() }
        }
    }
    ListView {
        id: messages
        objectName: "communicationMessages"
        y: header.height + 12 * reader.uiScale; width: parent.width; height: Math.max(0, parent.height - y)
        model: reader.provider.items
        clip: true; spacing: 12 * reader.uiScale; boundsBehavior: Flickable.StopAtBounds
        delegate: Rectangle {
            objectName: "messageRow"
            width: messages.width; height: messageText.y + messageText.height + 16 * reader.uiScale
            radius: 12; color: reader.palette.surface; clip: true
            Text {
                id: timestamp
                x: 16 * reader.uiScale; y: 12 * reader.uiScale; width: parent.width - 32 * reader.uiScale
                text: modelData.subtitle; wrapMode: Text.Wrap; color: reader.palette.secondary; font.pixelSize: 20 * reader.uiScale; textFormat: Text.PlainText
            }
            Text {
                id: messageText
                x: 16 * reader.uiScale; y: timestamp.y + timestamp.height + 8 * reader.uiScale; width: parent.width - 32 * reader.uiScale
                text: modelData.title; wrapMode: Text.Wrap; color: reader.palette.text; font.pixelSize: 28 * reader.uiScale; textFormat: Text.PlainText
            }
        }
        footer: Rectangle {
            width: messages.width; height: reader.provider.page.hasMore ? 60 * reader.uiScale : 0
            visible: reader.provider.page.hasMore === true; radius: 14; color: reader.buttonColor(moreTouch.pressed)
            Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Load more"); color: moreTouch.pressed ? reader.palette.highlightColor : reader.palette.text; font.pixelSize: 26 * reader.uiScale }
            MouseArea { id: moreTouch; anchors.fill: parent; enabled: !reader.provider.busy; onClicked: reader.provider.more() }
        }
    }
}
