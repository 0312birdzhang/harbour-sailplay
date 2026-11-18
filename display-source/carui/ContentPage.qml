import QtQuick 2.0

Rectangle {
    id: root
    property var provider
    property var palette
    property real uiScale: 1
    property var page: provider ? provider.page : ({})
    color: palette.card
    radius: 22
    clip: true

    Row {
        id: header
        x: 20 * root.uiScale; y: 16 * root.uiScale; width: parent.width - 40 * root.uiScale; height: 56 * root.uiScale; spacing: 16 * root.uiScale
        Rectangle {
            width: 76 * root.uiScale; height: parent.height; radius: 12; color: palette.button
            visible: !!provider && provider.canGoBack
            Text { anchors.centerIn: parent; text: "‹"; color: palette.text; font.pixelSize: 40 * root.uiScale }
            MouseArea { anchors.fill: parent; onClicked: provider.back() }
        }
        Text {
            width: Math.max(0, header.width - (provider && provider.canGoBack ? 92 : 0) * root.uiScale - 92 * root.uiScale)
            anchors.verticalCenter: parent.verticalCenter
            text: page.title || (provider ? provider.name : "")
            textFormat: Text.PlainText; color: palette.text; font.pixelSize: 30 * root.uiScale; elide: Text.ElideRight
        }
        Rectangle {
            width: 76 * root.uiScale; height: parent.height; radius: 12; color: palette.button
            Text { anchors.centerIn: parent; text: "↻"; color: palette.text; font.pixelSize: 32 * root.uiScale }
            MouseArea { anchors.fill: parent; enabled: !!provider && provider.ready && !provider.busy; onClicked: provider.refresh() }
        }
    }
    Rectangle {
        id: searchBox
        x: 20 * root.uiScale; y: header.y + header.height + 12 * root.uiScale; width: parent.width - 40 * root.uiScale; height: visible ? 58 * root.uiScale : 0
        visible: page.searchEnabled === true
        color: palette.button; radius: 12
        TextInput {
            id: searchInput
            objectName: "contentSearch"
            x: 16 * root.uiScale; width: parent.width - 120 * root.uiScale; height: parent.height
            color: palette.text; font.pixelSize: 26 * root.uiScale; verticalAlignment: TextInput.AlignVCenter
            clip: true; maximumLength: 256; selectByMouse: true
            onAccepted: { provider.search(text.trim()); focus = false }
            Text {
                anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                text: qsTranslate("Sailplay", "Search"); color: palette.secondary; font.pixelSize: 26 * root.uiScale
                visible: searchInput.text === "" && !searchInput.activeFocus
            }
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 20 * root.uiScale; anchors.verticalCenter: parent.verticalCenter
            text: "⌕"; color: palette.text; font.pixelSize: 32 * root.uiScale
            MouseArea { anchors.fill: parent; anchors.margins: -16; onClicked: { provider.search(searchInput.text.trim()); searchInput.focus = false } }
        }
    }
    Text {
        id: status
        x: 20 * root.uiScale; y: searchBox.y + searchBox.height + 8 * root.uiScale; width: parent.width - 40 * root.uiScale
        height: visible ? implicitHeight : 0
        text: provider && provider.error ? provider.error : !provider || !provider.ready
            ? qsTranslate("Sailplay", "Connecting content") : provider.busy
            ? qsTranslate("Sailplay", "Loading") : page.message || ""
        textFormat: Text.PlainText; color: palette.secondary; font.pixelSize: 24 * root.uiScale
        wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight; visible: text !== ""
    }
    ListView {
        id: list
        objectName: "contentList"
        x: 20 * root.uiScale; y: status.y + status.height + 8 * root.uiScale; width: parent.width - 40 * root.uiScale
        height: Math.max(0, controls.y - y - 12 * root.uiScale)
        clip: true; spacing: 8 * root.uiScale; boundsBehavior: Flickable.StopAtBounds
        model: provider ? provider.items : []
        delegate: Rectangle {
            objectName: "contentRow"
            width: list.width; height: Math.max(86 * root.uiScale, summary.height + 24 * root.uiScale); radius: 12
            clip: true
            color: area.pressed ? palette.notice : palette.button
            opacity: modelData.enabled ? 1 : 0.5
            Column {
                id: summary
                x: 16 * root.uiScale; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 64 * root.uiScale; spacing: 4 * root.uiScale
                Text { width: parent.width; text: (modelData.title || "").replace(/[\r\n\u2028\u2029]+/g, " "); textFormat: Text.PlainText; color: palette.text; font.pixelSize: 28 * root.uiScale; maximumLineCount: 1; elide: Text.ElideRight }
                Text { width: parent.width; text: (modelData.subtitle || "").replace(/[\r\n\u2028\u2029]+/g, " "); textFormat: Text.PlainText; color: palette.secondary; font.pixelSize: 22 * root.uiScale; maximumLineCount: 1; elide: Text.ElideRight; visible: text !== "" }
            }
            Text { anchors.right: parent.right; anchors.rightMargin: 20 * root.uiScale; anchors.verticalCenter: parent.verticalCenter; text: modelData.kind === "folder" ? "›" : "▶"; color: palette.text; font.pixelSize: 28 * root.uiScale }
            MouseArea { id: area; anchors.fill: parent; enabled: !!provider && modelData.enabled && provider.ready && !provider.busy; onClicked: provider.select(modelData.id) }
        }
        footer: Rectangle {
            width: list.width; height: page.hasMore ? 62 * root.uiScale : 0; color: palette.button; radius: 12; visible: page.hasMore === true
            Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Load more"); color: palette.text; font.pixelSize: 26 * root.uiScale }
            MouseArea { anchors.fill: parent; enabled: !!provider && !provider.busy; onClicked: provider.more() }
        }
    }
    Row {
        id: controls
        x: 20 * root.uiScale; y: root.height - height - 16 * root.uiScale; width: root.width - 40 * root.uiScale
        height: page.actions && page.actions.length ? 60 * root.uiScale : 0; spacing: 12 * root.uiScale
        Repeater {
            model: page.actions || []
            Rectangle {
                width: Math.max(0, (controls.width - controls.spacing * (page.actions.length - 1)) / page.actions.length)
                height: controls.height; radius: 12; color: palette.button
                Text { anchors.centerIn: parent; width: parent.width - 16 * root.uiScale; horizontalAlignment: Text.AlignHCenter; text: modelData.title; textFormat: Text.PlainText; color: palette.text; font.pixelSize: 24 * root.uiScale; elide: Text.ElideRight }
                MouseArea { anchors.fill: parent; enabled: !!provider && modelData.enabled && provider.ready && !provider.busy; onClicked: provider.action(modelData.id) }
            }
        }
    }
}
