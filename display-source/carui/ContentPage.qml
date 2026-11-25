import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica

// The browsing page of an application. The application chooses among standard
// arrangements; this page draws them with the ambience roles of CarPalette.
//   - tabs: the folders of a page shown as a bar above the selected one
//   - list, grid, wide: rows or cards of one size
//   - split: folders on the left, the selected one's rows on the right
//   - side: a pinned panel on the right, such as a play queue with its controls
Rectangle {
    id: root
    property var provider
    property var palette
    property real uiScale: 1
    // Optional transport of the application's player, shown in the side panel:
    // { available, playing, title, artist, canGoNext, canGoPrevious } with
    // playPause(), next() and previous().
    property var player
    property var page: provider ? provider.page : ({})
    property string layout: provider && provider.layout ? provider.layout : "list"
    property var tabs: provider && provider.tabs ? provider.tabs : []
    property var side: provider && provider.side && provider.side.id ? provider.side : null
    property var detail: provider && provider.detail ? provider.detail : ({})
    property bool usable: !!provider && provider.ready && !provider.busy
    property real margin: 20 * uiScale
    // Width left to browsing once the side panel has taken its share.
    property real mainWidth: width - 2 * margin - (side ? sidePanel.width + margin : 0)
    color: palette.overlayBackgroundColor
    radius: 22
    clip: true

    function plain(value) { return (value || "").replace(/[\r\n\u2028\u2029]+/g, " ") }
    function tint(colour, alpha) { return Qt.rgba(colour.r, colour.g, colour.b, alpha) }

    // A round touch target carrying a theme icon.
    Component {
        id: iconButton
        Rectangle {
            property string icon: ""
            property bool active: true
            signal clicked()
            width: 64 * root.uiScale; height: width; radius: width / 2
            color: iconArea.pressed ? root.tint(palette.highlightColor, 0.3) : root.tint(palette.highlightBackgroundColor, 0.55)
            opacity: active ? 1 : 0.4
            Image {
                anchors.centerIn: parent; width: parent.width * 0.62; height: width
                source: icon ? "image://theme/" + icon + "?" + (iconArea.pressed ? palette.highlightColor : palette.primaryColor) : ""
            }
            MouseArea { id: iconArea; anchors.fill: parent; enabled: parent.active; onClicked: parent.clicked() }
        }
    }

    Item {
        id: header
        x: root.margin; y: 14 * root.uiScale; width: root.mainWidth; height: 64 * root.uiScale
        Loader {
            id: backButton
            sourceComponent: iconButton
            visible: !!provider && provider.canGoBack
            width: visible ? 64 * root.uiScale : 0
            onLoaded: { item.icon = "icon-m-back"; item.clicked.connect(function() { provider.back() }) }
        }
        Text {
            x: backButton.width + (backButton.visible ? 16 * root.uiScale : 4 * root.uiScale)
            width: Math.max(0, refreshButton.x - x - 16 * root.uiScale)
            anchors.verticalCenter: parent.verticalCenter
            text: root.plain(page.title) || (provider ? provider.name : "")
            textFormat: Text.PlainText; color: palette.highlightColor
            font.pixelSize: 34 * root.uiScale; font.weight: Font.Light; elide: Text.ElideRight
        }
        Loader {
            id: refreshButton
            sourceComponent: iconButton
            x: parent.width - 64 * root.uiScale
            onLoaded: { item.icon = "icon-m-refresh"; item.clicked.connect(function() { if (provider.ready && !provider.busy) provider.refresh() }) }
        }
    }

    // Tabs keep one size and fill one line, then a second; further ones are reached by sliding the bar.
    Flickable {
        id: tabBar
        objectName: "contentTabs"
        property real gap: 10 * root.uiScale
        property real tabHeight: 62 * root.uiScale
        property int perLine: Math.max(1, Math.floor((width + gap) / (220 * root.uiScale + gap)))
        property real tabWidth: Math.floor((width + gap) / perLine - gap)
        property int lines: root.tabs.length > perLine ? 2 : 1
        x: root.margin; y: header.y + header.height + (visible ? 10 * root.uiScale : 0); width: root.mainWidth
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
                    width: tabBar.tabWidth; height: tabBar.tabHeight; radius: 12 * root.uiScale
                    color: tabArea.pressed ? root.tint(palette.highlightColor, 0.3)
                         : current ? root.tint(palette.highlightColor, 0.16) : root.tint(palette.highlightBackgroundColor, 0.55)
                    opacity: modelData.enabled ? 1 : 0.4
                    Text {
                        anchors.centerIn: parent; anchors.verticalCenterOffset: parent.current ? -5 * root.uiScale : 0
                        width: parent.width - 20 * root.uiScale; horizontalAlignment: Text.AlignHCenter
                        text: root.plain(modelData.title); textFormat: Text.PlainText
                        color: parent.current ? palette.highlightColor : palette.primaryColor
                        font.pixelSize: 26 * root.uiScale; maximumLineCount: 1; elide: Text.ElideRight
                    }
                    // The ambience glow marks the tab being shown.
                    Silica.GlassItem {
                        visible: parent.current
                        anchors.horizontalCenter: parent.horizontalCenter; y: parent.height - height / 2 - 7 * root.uiScale
                        width: 52 * root.uiScale; height: width
                        color: root.palette.highlightColor; falloffRadius: 0.2; radius: 0.2; cache: false
                    }
                    MouseArea { id: tabArea; anchors.fill: parent; enabled: root.usable && modelData.enabled; onClicked: provider.selectTab(modelData.id) }
                }
            }
        }
    }
    Rectangle {
        id: searchBox
        x: root.margin; y: tabBar.y + tabBar.height + (visible ? 10 * root.uiScale : 0); width: root.mainWidth; height: visible ? 58 * root.uiScale : 0
        visible: page.searchEnabled === true
        color: root.tint(palette.highlightBackgroundColor, 0.55); radius: 12 * root.uiScale
        TextInput {
            id: searchInput
            objectName: "contentSearch"
            x: 16 * root.uiScale; width: parent.width - 96 * root.uiScale; height: parent.height
            color: palette.primaryColor; font.pixelSize: 26 * root.uiScale; verticalAlignment: TextInput.AlignVCenter
            clip: true; maximumLength: 256; selectByMouse: true
            onAccepted: { provider.search(text.trim()); focus = false }
            Text {
                anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                text: qsTranslate("Sailplay", "Search"); color: palette.secondaryColor; font.pixelSize: 26 * root.uiScale
                visible: searchInput.text === "" && !searchInput.activeFocus
            }
        }
        Image {
            anchors.right: parent.right; anchors.rightMargin: 16 * root.uiScale; anchors.verticalCenter: parent.verticalCenter
            width: 40 * root.uiScale; height: width; source: "image://theme/icon-m-search?" + palette.primaryColor
            MouseArea { anchors.fill: parent; anchors.margins: -16; onClicked: { provider.search(searchInput.text.trim()); searchInput.focus = false } }
        }
    }
    Text {
        id: status
        x: root.margin; y: searchBox.y + searchBox.height + 8 * root.uiScale; width: root.mainWidth
        height: visible ? implicitHeight : 0
        text: provider && provider.error ? provider.error : !provider || !provider.ready
            ? qsTranslate("Sailplay", "Connecting content") : provider.busy
            ? qsTranslate("Sailplay", "Loading") : page.message || ""
        textFormat: Text.PlainText; color: palette.secondaryColor; font.pixelSize: 24 * root.uiScale
        wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight; visible: text !== ""
    }

    Item {
        id: body
        x: root.margin; y: status.y + status.height + 8 * root.uiScale; width: root.mainWidth
        height: Math.max(0, controls.y - y - 12 * root.uiScale)
        property bool split: root.layout === "split"
        property real masterWidth: split ? Math.round(Math.min(width * 0.36, 440 * root.uiScale)) : width

        // The rows of the page; in a split page, the folders to choose from.
        ContentPane {
            id: mainPane
            palette: root.palette; uiScale: root.uiScale
            width: body.masterWidth; height: parent.height
            items: provider ? provider.items : []
            layout: body.split ? "list" : root.layout
            compact: body.split
            currentId: body.split && provider && provider.currentItem ? provider.currentItem : ""
            hasMore: page.hasMore === true
            usable: root.usable
            onActivated: provider.select(id)
            onMoreRequested: provider.more()
        }
        // In a split page, the rows of the chosen folder.
        Item {
            visible: body.split
            x: body.masterWidth + root.margin; width: parent.width - x; height: parent.height
            Text {
                id: detailTitle
                width: parent.width; height: 36 * root.uiScale; horizontalAlignment: Text.AlignRight
                text: root.plain(root.detail.title); textFormat: Text.PlainText; elide: Text.ElideRight
                color: palette.secondaryHighlightColor; font.pixelSize: 24 * root.uiScale
            }
            Text {
                y: detailTitle.height + 12 * root.uiScale; width: parent.width
                visible: !!root.detail.message && !(root.detail.items && root.detail.items.length)
                text: root.plain(root.detail.message); textFormat: Text.PlainText; wrapMode: Text.WordWrap
                color: palette.secondaryColor; font.pixelSize: 24 * root.uiScale
            }
            ContentPane {
                palette: root.palette; uiScale: root.uiScale
                y: detailTitle.height + 6 * root.uiScale; width: parent.width; height: parent.height - y
                listName: "contentDetailList"; rowName: "contentDetailRow"
                items: root.detail.items || []
                layout: root.detail.layout || "list"
                hasMore: root.detail.hasMore === true
                usable: root.usable
                onActivated: provider.selectDetail(id)
                onMoreRequested: provider.moreDetail()
            }
        }
    }

    Row {
        id: controls
        x: root.margin; y: root.height - height - 16 * root.uiScale; width: root.mainWidth
        height: page.actions && page.actions.length ? 60 * root.uiScale : 0; spacing: 12 * root.uiScale
        Repeater {
            model: page.actions || []
            Rectangle {
                width: Math.max(0, (controls.width - controls.spacing * (page.actions.length - 1)) / page.actions.length)
                height: controls.height; radius: 12 * root.uiScale
                color: actionArea.pressed ? root.tint(palette.highlightColor, 0.3) : root.tint(palette.highlightBackgroundColor, 0.55)
                opacity: modelData.enabled ? 1 : 0.4
                Text { anchors.centerIn: parent; width: parent.width - 16 * root.uiScale; horizontalAlignment: Text.AlignHCenter; text: root.plain(modelData.title); textFormat: Text.PlainText; color: palette.primaryColor; font.pixelSize: 24 * root.uiScale; elide: Text.ElideRight }
                MouseArea { id: actionArea; anchors.fill: parent; enabled: root.usable && modelData.enabled; onClicked: provider.action(modelData.id) }
            }
        }
    }

    // A pinned panel: what is playing, its transport, the queue and its options.
    Rectangle {
        id: sidePanel
        objectName: "contentSide"
        visible: !!root.side
        x: root.width - width - root.margin; y: 14 * root.uiScale
        width: visible ? Math.round(Math.min(root.width * 0.36, 620 * root.uiScale)) : 0
        height: root.height - 28 * root.uiScale
        radius: 18 * root.uiScale
        color: root.tint(palette.highlightDimmerColor, 0.55)
        property real pad: 16 * root.uiScale
        property bool transport: !!root.player && root.player.available === true

        Text {
            id: sideTitle
            x: sidePanel.pad; y: 10 * root.uiScale; width: parent.width - 2 * sidePanel.pad; height: 34 * root.uiScale
            horizontalAlignment: Text.AlignRight
            text: root.side ? root.plain(root.side.title) : ""; textFormat: Text.PlainText; elide: Text.ElideRight
            color: palette.secondaryHighlightColor; font.pixelSize: 24 * root.uiScale
        }
        Item {
            id: nowPlaying
            x: sidePanel.pad; y: sideTitle.y + sideTitle.height + 6 * root.uiScale; width: parent.width - 2 * sidePanel.pad
            height: sidePanel.transport ? 132 * root.uiScale : 0; visible: sidePanel.transport
            Column {
                width: parent.width
                Text {
                    width: parent.width; text: root.player ? root.plain(root.player.title) : ""; textFormat: Text.PlainText
                    color: palette.highlightColor; font.pixelSize: 26 * root.uiScale; maximumLineCount: 1; elide: Text.ElideRight
                }
                Text {
                    width: parent.width; text: root.player ? root.plain(root.player.artist) : ""; textFormat: Text.PlainText
                    color: palette.secondaryHighlightColor; font.pixelSize: 21 * root.uiScale; maximumLineCount: 1; elide: Text.ElideRight
                }
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter; y: 62 * root.uiScale; spacing: 36 * root.uiScale
                Loader {
                    sourceComponent: iconButton
                    onLoaded: {
                        item.icon = "icon-m-previous"; item.active = Qt.binding(function() { return !!root.player && root.player.canGoPrevious })
                        item.clicked.connect(function() { root.player.previous() })
                    }
                }
                Loader {
                    sourceComponent: iconButton
                    onLoaded: {
                        item.width = 72 * root.uiScale
                        item.icon = Qt.binding(function() { return root.player && root.player.playing ? "icon-m-pause" : "icon-m-play" })
                        item.clicked.connect(function() { root.player.playPause() })
                    }
                }
                Loader {
                    sourceComponent: iconButton
                    onLoaded: {
                        item.icon = "icon-m-next"; item.active = Qt.binding(function() { return !!root.player && root.player.canGoNext })
                        item.clicked.connect(function() { root.player.next() })
                    }
                }
            }
        }
        Text {
            x: sidePanel.pad; y: sideList.y + 8 * root.uiScale; width: sideList.width
            visible: !!root.side && !!root.side.message && !(root.side.items && root.side.items.length)
            text: root.side ? root.plain(root.side.message) : ""; textFormat: Text.PlainText; wrapMode: Text.WordWrap
            color: palette.secondaryColor; font.pixelSize: 22 * root.uiScale
        }
        ContentPane {
            id: sideList
            palette: root.palette; uiScale: root.uiScale
            x: sidePanel.pad; y: nowPlaying.y + nowPlaying.height + 8 * root.uiScale
            width: parent.width - 2 * sidePanel.pad; height: Math.max(0, sideOptions.y - y - 10 * root.uiScale)
            listName: "contentSideList"; rowName: "contentSideRow"
            items: root.side && root.side.items ? root.side.items : []
            layout: "list"; compact: true
            hasMore: !!root.side && root.side.hasMore === true
            usable: root.usable
            onActivated: provider.selectSide(id)
            onMoreRequested: provider.moreSide()
        }
        Row {
            id: sideOptions
            property var entries: root.side && root.side.actions ? root.side.actions : []
            x: sidePanel.pad; y: parent.height - height - 12 * root.uiScale; width: parent.width - 2 * sidePanel.pad
            height: entries.length ? 56 * root.uiScale : 0; spacing: 10 * root.uiScale
            Repeater {
                model: sideOptions.entries
                Rectangle {
                    width: Math.max(0, (sideOptions.width - sideOptions.spacing * (sideOptions.entries.length - 1)) / sideOptions.entries.length)
                    height: sideOptions.height; radius: 12 * root.uiScale
                    color: optionArea.pressed ? root.tint(palette.highlightColor, 0.3) : root.tint(palette.highlightBackgroundColor, 0.55)
                    opacity: modelData.enabled ? 1 : 0.4
                    Text { anchors.centerIn: parent; width: parent.width - 12 * root.uiScale; horizontalAlignment: Text.AlignHCenter; text: root.plain(modelData.title); textFormat: Text.PlainText; color: palette.primaryColor; font.pixelSize: 22 * root.uiScale; elide: Text.ElideRight }
                    MouseArea { id: optionArea; anchors.fill: parent; enabled: root.usable && modelData.enabled; onClicked: provider.sideAction(modelData.id) }
                }
            }
        }
    }
}
