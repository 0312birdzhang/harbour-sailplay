import QtQuick 2.0

Rectangle {
    id: root
    property var provider
    property var palette
    property var page: provider ? provider.page : ({})
    color: palette.card
    radius: 22
    clip: true

    Row {
        id: header
        x: 20; y: 16; width: parent.width - 40; height: 56; spacing: 16
        Rectangle {
            width: 76; height: parent.height; radius: 12; color: palette.button
            visible: !!provider && provider.canGoBack
            Text { anchors.centerIn: parent; text: "‹"; color: palette.text; font.pixelSize: 40 }
            MouseArea { anchors.fill: parent; onClicked: provider.back() }
        }
        Text {
            width: Math.max(0, header.width - (provider && provider.canGoBack ? 92 : 0) - 92)
            anchors.verticalCenter: parent.verticalCenter
            text: page.title || (provider ? provider.name : "")
            textFormat: Text.PlainText; color: palette.text; font.pixelSize: 30; elide: Text.ElideRight
        }
        Rectangle {
            width: 76; height: parent.height; radius: 12; color: palette.button
            Text { anchors.centerIn: parent; text: "↻"; color: palette.text; font.pixelSize: 32 }
            MouseArea { anchors.fill: parent; enabled: !!provider && provider.ready && !provider.busy; onClicked: provider.refresh() }
        }
    }
    Rectangle {
        id: searchBox
        x: 20; y: header.y + header.height + 12; width: parent.width - 40; height: visible ? 58 : 0
        visible: page.searchEnabled === true
        color: palette.button; radius: 12
        TextInput {
            id: searchInput
            objectName: "contentSearch"
            x: 16; width: parent.width - 120; height: parent.height
            color: palette.text; font.pixelSize: 26; verticalAlignment: TextInput.AlignVCenter
            clip: true; maximumLength: 256; selectByMouse: true
            onAccepted: { provider.search(text.trim()); focus = false }
            Text {
                anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                text: qsTranslate("Sailplay", "Search"); color: palette.secondary; font.pixelSize: 26
                visible: searchInput.text === "" && !searchInput.activeFocus
            }
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 20; anchors.verticalCenter: parent.verticalCenter
            text: "⌕"; color: palette.text; font.pixelSize: 32
            MouseArea { anchors.fill: parent; anchors.margins: -16; onClicked: { provider.search(searchInput.text.trim()); searchInput.focus = false } }
        }
    }
    Text {
        id: status
        x: 20; y: searchBox.y + searchBox.height + 8; width: parent.width - 40
        height: visible ? implicitHeight : 0
        text: provider && provider.error ? provider.error : !provider || !provider.ready
            ? qsTranslate("Sailplay", "Connecting content") : provider.busy
            ? qsTranslate("Sailplay", "Loading") : page.message || ""
        textFormat: Text.PlainText; color: palette.secondary; font.pixelSize: 24
        wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight; visible: text !== ""
    }
    ListView {
        id: list
        objectName: "contentList"
        x: 20; y: status.y + status.height + 8; width: parent.width - 40
        height: Math.max(0, controls.y - y - 12)
        clip: true; spacing: 8; boundsBehavior: Flickable.StopAtBounds
        model: provider ? provider.items : []
        delegate: Rectangle {
            width: list.width; height: 86; radius: 12
            color: area.pressed ? palette.notice : palette.button
            opacity: modelData.enabled ? 1 : 0.5
            Column {
                x: 16; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 64; spacing: 4
                Text { width: parent.width; text: modelData.title; textFormat: Text.PlainText; color: palette.text; font.pixelSize: 28; elide: Text.ElideRight }
                Text { width: parent.width; text: modelData.subtitle; textFormat: Text.PlainText; color: palette.secondary; font.pixelSize: 22; elide: Text.ElideRight; visible: text !== "" }
            }
            Text { anchors.right: parent.right; anchors.rightMargin: 20; anchors.verticalCenter: parent.verticalCenter; text: modelData.kind === "folder" ? "›" : "▶"; color: palette.text; font.pixelSize: 28 }
            MouseArea { id: area; anchors.fill: parent; enabled: !!provider && modelData.enabled && provider.ready && !provider.busy; onClicked: provider.select(modelData.id) }
        }
        footer: Rectangle {
            width: list.width; height: page.hasMore ? 62 : 0; color: palette.button; radius: 12; visible: page.hasMore === true
            Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Load more"); color: palette.text; font.pixelSize: 26 }
            MouseArea { anchors.fill: parent; enabled: !!provider && !provider.busy; onClicked: provider.more() }
        }
    }
    Row {
        id: controls
        x: 20; y: root.height - height - 16; width: root.width - 40
        height: page.actions && page.actions.length ? 60 : 0; spacing: 12
        Repeater {
            model: page.actions || []
            Rectangle {
                width: Math.max(0, (controls.width - 12 * (page.actions.length - 1)) / page.actions.length)
                height: controls.height; radius: 12; color: palette.button
                Text { anchors.centerIn: parent; width: parent.width - 16; horizontalAlignment: Text.AlignHCenter; text: modelData.title; textFormat: Text.PlainText; color: palette.text; font.pixelSize: 24; elide: Text.ElideRight }
                MouseArea { anchors.fill: parent; enabled: !!provider && modelData.enabled && provider.ready && !provider.busy; onClicked: provider.action(modelData.id) }
            }
        }
    }
}
