import QtQuick 2.0

Item {
    id: reader
    property var palette
    property var provider
    signal reply()
    Row {
        id: header
        width: parent.width; height: 60; spacing: 12
        Rectangle {
            width: 120; height: parent.height; radius: 12; color: reader.palette.button
            Text { anchors.centerIn: parent; text: "‹"; color: reader.palette.text; font.pixelSize: 36 }
            MouseArea { anchors.fill: parent; onClicked: reader.provider.back() }
        }
        Text {
            width: Math.max(0, parent.width - 280); height: parent.height
            verticalAlignment: Text.AlignVCenter; font.pixelSize: 28; color: reader.palette.text
            text: reader.provider.page.title || ""; elide: Text.ElideRight; textFormat: Text.PlainText
        }
        Rectangle {
            width: 136; height: parent.height; radius: 12; color: reader.palette.button
            Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Reply"); color: reader.palette.text; font.pixelSize: 26 }
            MouseArea { anchors.fill: parent; enabled: reader.provider.ready && !reader.provider.busy; onClicked: reader.reply() }
        }
    }
    ListView {
        id: messages
        y: header.height + 12; width: parent.width; height: Math.max(0, parent.height - y)
        model: reader.provider.items
        clip: true; spacing: 12; boundsBehavior: Flickable.StopAtBounds
        delegate: Rectangle {
            width: messages.width; height: messageText.height + timestamp.height + 36
            radius: 12; color: reader.palette.card
            Text {
                id: timestamp
                x: 16; y: 12; width: parent.width - 32
                text: modelData.subtitle; color: reader.palette.secondary; font.pixelSize: 20; textFormat: Text.PlainText
            }
            Text {
                id: messageText
                x: 16; y: timestamp.y + timestamp.height + 8; width: parent.width - 32
                text: modelData.title; wrapMode: Text.Wrap; color: reader.palette.text; font.pixelSize: 28; textFormat: Text.PlainText
            }
        }
        footer: Rectangle {
            width: messages.width; height: reader.provider.page.hasMore ? 60 : 0
            visible: reader.provider.page.hasMore === true; radius: 12; color: reader.palette.button
            Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Load more"); color: reader.palette.text; font.pixelSize: 26 }
            MouseArea { anchors.fill: parent; enabled: !reader.provider.busy; onClicked: reader.provider.more() }
        }
    }
}
