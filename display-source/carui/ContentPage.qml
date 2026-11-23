import QtQuick 2.0

Rectangle {
    id: root
    property var provider
    property var palette
    property real uiScale: 1
    property var page: provider ? provider.page : ({})
    // Standard arrangements chosen by the application: "list", "grid" or "wide".
    property string layout: provider && provider.layout ? provider.layout : "list"
    property var tabs: provider && provider.tabs ? provider.tabs : []
    property bool usable: !!provider && provider.ready && !provider.busy
    color: palette.card
    radius: 22
    clip: true

    function plain(value) { return (value || "").replace(/[\r\n\u2028\u2029]+/g, " ") }
    function imageSource(value) { return !value ? "" : value.charAt(0) === "/" ? "file://" + value : value }

    // Playback status of a row, readable at a glance: a dot for something new,
    // a half disc once started, a play mark while playing, a tick when finished.
    Component {
        id: badge
        Item {
            property string playback: ""
            property real size: 34 * root.uiScale
            width: size; height: size; visible: playback !== ""
            Rectangle {
                anchors.fill: parent; radius: width / 2
                color: playback === "playing" ? palette.positive : playback === "finished" ? palette.disabled : palette.card
                border.width: playback === "unplayed" || playback === "started" ? 3 * root.uiScale : 0
                border.color: palette.positive
            }
            Rectangle {
                visible: playback === "unplayed"
                anchors.centerIn: parent; width: parent.width * 0.4; height: width; radius: width / 2; color: palette.positive
            }
            Item {
                visible: playback === "started"
                x: parent.width / 2; width: parent.width / 2; height: parent.height; clip: true
                Rectangle { x: -parent.width; width: parent.height; height: parent.height; radius: width / 2; color: palette.positive }
            }
            Text {
                visible: playback === "playing" || playback === "finished"
                anchors.centerIn: parent; text: playback === "playing" ? "▶" : "✓"
                color: palette.actionText; font.pixelSize: parent.height * 0.55; font.bold: true
            }
        }
    }

    // The picture of a row, or its initial on a plain tile when it has none.
    Component {
        id: picture
        Rectangle {
            property string source: ""
            property string label: ""
            property bool folder: false
            radius: 10 * root.uiScale; color: palette.tile; clip: true
            Text {
                anchors.centerIn: parent; visible: art.status !== Image.Ready
                text: folder && label === "" ? "›" : label.charAt(0).toUpperCase()
                color: palette.text; font.pixelSize: parent.height * 0.5; font.bold: true
            }
            Image {
                id: art
                anchors.fill: parent; source: root.imageSource(parent.source); asynchronous: true; cache: true
                fillMode: Image.PreserveAspectCrop; sourceSize.width: 320; sourceSize.height: 320
                visible: status === Image.Ready
            }
        }
    }

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
    // Tabs keep one size and fill one line, then a second; further ones are reached by sliding the bar.
    Flickable {
        id: tabBar
        objectName: "contentTabs"
        property real tabWidth: 230 * root.uiScale
        property real tabHeight: 64 * root.uiScale
        property real gap: 10 * root.uiScale
        property int perLine: Math.max(1, Math.floor((width + gap) / (tabWidth + gap)))
        property int lines: root.tabs.length > perLine ? 2 : 1
        x: 20 * root.uiScale; y: header.y + header.height + (visible ? 12 * root.uiScale : 0); width: parent.width - 40 * root.uiScale
        height: visible ? lines * tabHeight + (lines - 1) * gap : 0
        visible: root.tabs.length > 0
        clip: true; boundsBehavior: Flickable.StopAtBounds; flickableDirection: Flickable.HorizontalFlick
        contentWidth: tabGrid.width; contentHeight: height
        Grid {
            id: tabGrid
            rows: tabBar.lines; columns: Math.max(tabBar.perLine, Math.ceil(root.tabs.length / tabBar.lines))
            spacing: tabBar.gap
            Repeater {
                model: root.tabs
                Rectangle {
                    objectName: "contentTab"
                    property bool current: !!provider && provider.currentTab === modelData.id
                    width: tabBar.tabWidth; height: tabBar.tabHeight; radius: 12
                    color: current ? palette.pressed : tabArea.pressed ? palette.notice : palette.button
                    border.width: current ? 3 * root.uiScale : 0; border.color: palette.text
                    opacity: modelData.enabled ? 1 : 0.5
                    Text {
                        anchors.centerIn: parent; width: parent.width - 20 * root.uiScale; horizontalAlignment: Text.AlignHCenter
                        text: root.plain(modelData.title); textFormat: Text.PlainText; color: palette.text
                        font.pixelSize: 26 * root.uiScale; font.bold: parent.current; maximumLineCount: 1; elide: Text.ElideRight
                    }
                    MouseArea { id: tabArea; anchors.fill: parent; enabled: root.usable && modelData.enabled; onClicked: provider.selectTab(modelData.id) }
                }
            }
        }
    }
    Rectangle {
        id: searchBox
        x: 20 * root.uiScale; y: tabBar.y + tabBar.height + 12 * root.uiScale; width: parent.width - 40 * root.uiScale; height: visible ? 58 * root.uiScale : 0
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
        visible: root.layout === "list"
        x: 20 * root.uiScale; y: status.y + status.height + 8 * root.uiScale; width: parent.width - 40 * root.uiScale
        height: Math.max(0, controls.y - y - 12 * root.uiScale)
        clip: true; spacing: 8 * root.uiScale; boundsBehavior: Flickable.StopAtBounds
        model: provider && visible ? provider.items : []
        delegate: Rectangle {
            objectName: "contentRow"
            property bool pictured: !!modelData.image
            width: list.width; height: Math.max(86 * root.uiScale, summary.height + 24 * root.uiScale); radius: 12
            clip: true
            color: area.pressed ? palette.notice : palette.button
            opacity: modelData.enabled ? 1 : 0.5
            Loader {
                id: rowPicture
                active: parent.pictured; sourceComponent: picture
                x: 12 * root.uiScale; anchors.verticalCenter: parent.verticalCenter
                width: active ? 66 * root.uiScale : 0; height: 66 * root.uiScale
                onLoaded: { item.source = modelData.image; item.label = root.plain(modelData.title); item.width = width; item.height = height }
            }
            Column {
                id: summary
                x: (parent.pictured ? 94 : 16) * root.uiScale; anchors.verticalCenter: parent.verticalCenter
                width: parent.width - x - (modelData.playback ? 112 : 64) * root.uiScale; spacing: 4 * root.uiScale
                Text { width: parent.width; text: root.plain(modelData.title); textFormat: Text.PlainText; color: palette.text; font.pixelSize: 28 * root.uiScale; maximumLineCount: 1; elide: Text.ElideRight }
                Text { width: parent.width; text: root.plain(modelData.subtitle); textFormat: Text.PlainText; color: palette.secondary; font.pixelSize: 22 * root.uiScale; maximumLineCount: 1; elide: Text.ElideRight; visible: text !== "" }
            }
            Loader {
                active: !!modelData.playback; sourceComponent: badge
                anchors.right: parent.right; anchors.rightMargin: 60 * root.uiScale; anchors.verticalCenter: parent.verticalCenter
                onLoaded: item.playback = modelData.playback
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
    // Cards keep one size whatever their text; the whole card is the touch target.
    GridView {
        id: grid
        objectName: "contentGrid"
        property bool wide: root.layout === "wide"
        property real gap: 12 * root.uiScale
        // Every card of a page has the same size; columns share the width evenly.
        property real room: root.width - 40 * root.uiScale
        property int columns: Math.max(1, Math.floor((room + gap) / ((wide ? 430 : 210) * root.uiScale + gap)))
        property real cardWidth: Math.floor((room + gap) / columns - gap)
        property real cardHeight: (wide ? 124 : 204) * root.uiScale
        visible: root.layout !== "list"
        x: 20 * root.uiScale; y: list.y; height: list.height
        width: columns * (cardWidth + gap)
        cellWidth: cardWidth + gap; cellHeight: cardHeight + gap
        clip: true; boundsBehavior: Flickable.StopAtBounds
        model: provider && visible ? provider.items : []
        delegate: Item {
            width: grid.cellWidth; height: grid.cellHeight
            Rectangle {
                objectName: "contentCard"
                width: grid.cardWidth; height: grid.cardHeight; radius: 14
                color: cardArea.pressed ? palette.notice : palette.button
                border.width: modelData.playback === "playing" ? 4 * root.uiScale : 0; border.color: palette.positive
                opacity: modelData.enabled ? 1 : 0.5
                Loader {
                    id: cardPicture
                    sourceComponent: picture
                    property real side: (grid.wide ? 100 : 112) * root.uiScale
                    x: grid.wide ? 12 * root.uiScale : (parent.width - side) / 2; y: 12 * root.uiScale
                    width: side; height: side
                    onLoaded: {
                        item.source = modelData.image || ""; item.label = root.plain(modelData.title)
                        item.folder = modelData.kind === "folder"; item.width = side; item.height = side
                    }
                }
                Column {
                    x: grid.wide ? cardPicture.x + cardPicture.width + 14 * root.uiScale : 10 * root.uiScale
                    y: grid.wide ? 0 : cardPicture.y + cardPicture.height + 6 * root.uiScale
                    width: parent.width - x - (grid.wide && (modelData.playback || modelData.kind === "folder") ? 50 : 10) * root.uiScale
                    height: grid.wide ? parent.height : parent.height - y - 6 * root.uiScale
                    Item { width: 1; height: grid.wide ? Math.max(0, (parent.height - cardTitle.height - cardSubtitle.height) / 2) : 0 }
                    Text {
                        id: cardTitle
                        width: parent.width; text: root.plain(modelData.title); textFormat: Text.PlainText; color: palette.text
                        font.pixelSize: 24 * root.uiScale; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
                        horizontalAlignment: grid.wide ? Text.AlignLeft : Text.AlignHCenter
                    }
                    Text {
                        id: cardSubtitle
                        width: parent.width; height: visible ? implicitHeight : 0
                        visible: grid.wide && text !== ""
                        text: root.plain(modelData.subtitle); textFormat: Text.PlainText; color: palette.secondary
                        font.pixelSize: 20 * root.uiScale; maximumLineCount: 1; elide: Text.ElideRight
                    }
                }
                Loader {
                    active: !!modelData.playback; sourceComponent: badge
                    anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8 * root.uiScale
                    onLoaded: item.playback = modelData.playback
                }
                Text {
                    // A folder opens another page instead of starting something.
                    visible: modelData.kind === "folder" && !modelData.playback
                    anchors.right: parent.right; anchors.top: parent.top; anchors.rightMargin: 14 * root.uiScale; anchors.topMargin: 4 * root.uiScale
                    text: "›"; color: palette.secondary; font.pixelSize: 34 * root.uiScale
                }
                MouseArea { id: cardArea; anchors.fill: parent; enabled: root.usable && modelData.enabled; onClicked: provider.select(modelData.id) }
            }
        }
        footer: Item {
            width: grid.width; height: page.hasMore === true ? 74 * root.uiScale : 0; visible: page.hasMore === true
            Rectangle {
                width: parent.width - grid.gap; height: 62 * root.uiScale; color: palette.button; radius: 12
                Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Load more"); color: palette.text; font.pixelSize: 26 * root.uiScale }
                MouseArea { anchors.fill: parent; enabled: !!provider && !provider.busy; onClicked: provider.more() }
            }
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
