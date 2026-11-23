import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica

// One scrolling area of content rows, drawn as a list or as cards of one size.
// It only uses the ambience roles of CarPalette, like the music page.
Item {
    id: pane
    property var palette
    property real uiScale: 1
    property var items: []
    // "list", "grid" (square cards) or "wide" (rectangular cards).
    property string layout: "list"
    property bool hasMore: false
    property bool usable: true
    // Row shown as the current choice of a master list.
    property string currentId: ""
    // Narrow columns use shorter rows and no pictures.
    property bool compact: false
    property string listName: "contentList"
    property string rowName: "contentRow"
    signal activated(string id)
    signal moreRequested()
    clip: true

    function plain(value) { return (value || "").replace(/[\r\n\u2028\u2029]+/g, " ") }
    function imageSource(value) { return !value ? "" : value.charAt(0) === "/" ? "file://" + value : value }
    function tint(colour, alpha) { return Qt.rgba(colour.r, colour.g, colour.b, alpha) }
    function lit(row) { return row.playback === "playing" || (currentId !== "" && row.id === currentId) }

    // Playback status of a row: the ambience glow while it plays, a dot when
    // new, a half disc once started and a dimmed tick when finished.
    Component {
        id: badge
        Item {
            property string playback: ""
            property real size: 34 * pane.uiScale
            width: size; height: size; visible: playback !== ""
            Silica.GlassItem {
                visible: playback === "playing"
                anchors.centerIn: parent; width: parent.width * 1.9; height: width
                color: pane.palette.highlightColor; falloffRadius: 0.2; radius: 0.2; cache: false
            }
            Rectangle {
                visible: playback === "unplayed"
                anchors.centerIn: parent; width: parent.width * 0.42; height: width; radius: width / 2
                color: palette.secondaryHighlightColor
            }
            Item {
                visible: playback === "started"
                anchors.centerIn: parent; width: parent.width * 0.62; height: width
                Rectangle { anchors.fill: parent; radius: width / 2; color: "transparent"; border.width: 2 * pane.uiScale; border.color: palette.secondaryHighlightColor }
                Item {
                    x: parent.width / 2; width: parent.width / 2; height: parent.height; clip: true
                    Rectangle { x: -parent.width; width: parent.height; height: parent.height; radius: width / 2; color: palette.secondaryHighlightColor }
                }
            }
            Image {
                visible: playback === "finished"
                anchors.centerIn: parent; width: parent.width * 0.8; height: width; opacity: 0.6
                source: "image://theme/icon-s-checkmark?" + palette.secondaryColor
            }
        }
    }

    // The picture of a row, or its initial on a plain tile when it has none.
    Component {
        id: picture
        Rectangle {
            property string source: ""
            property string label: ""
            radius: 10 * pane.uiScale; color: pane.tint(palette.highlightColor, 0.12); clip: true
            Text {
                anchors.centerIn: parent; visible: art.status !== Image.Ready
                text: label.charAt(0).toUpperCase()
                color: palette.secondaryHighlightColor; font.pixelSize: parent.height * 0.5; font.weight: Font.Light
            }
            Image {
                id: art
                anchors.fill: parent; source: pane.imageSource(parent.source); asynchronous: true; cache: true
                fillMode: Image.PreserveAspectCrop; sourceSize.width: 320; sourceSize.height: 320
                visible: status === Image.Ready
            }
        }
    }

    ListView {
        id: list
        objectName: pane.listName
        anchors.fill: parent
        visible: pane.layout === "list"
        clip: true; spacing: 8 * pane.uiScale; boundsBehavior: Flickable.StopAtBounds
        model: visible ? pane.items : []
        delegate: Rectangle {
            objectName: pane.rowName
            property bool pictured: !pane.compact && !!modelData.image
            property bool lit: pane.lit(modelData)
            width: list.width; height: (pane.compact ? 72 : 84) * pane.uiScale; radius: 12 * pane.uiScale
            clip: true
            color: area.pressed ? pane.tint(palette.highlightColor, 0.3)
                 : lit ? pane.tint(palette.highlightColor, 0.16) : pane.tint(palette.highlightBackgroundColor, 0.55)
            opacity: modelData.enabled ? 1 : 0.4
            Silica.GlassItem {
                visible: parent.lit
                x: -width / 2 + 6 * pane.uiScale; anchors.verticalCenter: parent.verticalCenter
                width: 56 * pane.uiScale; height: width
                color: pane.palette.highlightColor; falloffRadius: 0.2; radius: 0.2; cache: false
            }
            Loader {
                id: rowPicture
                active: parent.pictured; sourceComponent: picture
                x: 18 * pane.uiScale; anchors.verticalCenter: parent.verticalCenter
                width: active ? 64 * pane.uiScale : 0; height: 64 * pane.uiScale
                onLoaded: { item.source = modelData.image; item.label = pane.plain(modelData.title) }
            }
            Column {
                id: summary
                x: (parent.pictured ? 98 : 24) * pane.uiScale; anchors.verticalCenter: parent.verticalCenter
                width: parent.width - x - (trailing.width + 28 * pane.uiScale); spacing: 2 * pane.uiScale
                Text {
                    width: parent.width; text: pane.plain(modelData.title); textFormat: Text.PlainText
                    color: lit ? palette.highlightColor : palette.primaryColor
                    font.pixelSize: (pane.compact ? 25 : 28) * pane.uiScale; maximumLineCount: 1; elide: Text.ElideRight
                }
                Text {
                    width: parent.width; text: pane.plain(modelData.subtitle); textFormat: Text.PlainText
                    color: lit ? palette.secondaryHighlightColor : palette.secondaryColor
                    font.pixelSize: (pane.compact ? 20 : 22) * pane.uiScale; maximumLineCount: 1; elide: Text.ElideRight; visible: text !== ""
                }
            }
            Row {
                id: trailing
                anchors.right: parent.right; anchors.rightMargin: 14 * pane.uiScale; anchors.verticalCenter: parent.verticalCenter
                spacing: 4 * pane.uiScale
                Loader {
                    active: !!modelData.playback && modelData.playback !== "playing"; sourceComponent: badge
                    anchors.verticalCenter: parent.verticalCenter
                    onLoaded: item.playback = modelData.playback
                }
                Image {
                    visible: modelData.kind === "folder" && pane.currentId === ""
                    anchors.verticalCenter: parent.verticalCenter; width: 36 * pane.uiScale; height: width
                    source: "image://theme/icon-m-right?" + palette.secondaryColor
                }
            }
            MouseArea { id: area; anchors.fill: parent; enabled: pane.usable && modelData.enabled; onClicked: pane.activated(modelData.id) }
        }
        footer: Item {
            width: list.width; height: pane.hasMore ? 70 * pane.uiScale : 0; visible: pane.hasMore
            Rectangle {
                y: 8 * pane.uiScale; width: parent.width; height: 62 * pane.uiScale; radius: 12 * pane.uiScale
                color: moreArea.pressed ? pane.tint(palette.highlightColor, 0.3) : pane.tint(palette.highlightBackgroundColor, 0.55)
                Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Load more"); color: palette.highlightColor; font.pixelSize: 26 * pane.uiScale }
                MouseArea { id: moreArea; anchors.fill: parent; enabled: pane.usable; onClicked: pane.moreRequested() }
            }
        }
    }

    // Cards keep one size whatever their text; the whole card is the touch target.
    GridView {
        id: grid
        objectName: "contentGrid"
        property bool wide: pane.layout === "wide"
        property real gap: 12 * pane.uiScale
        // Every card of a page has the same size; columns share the width evenly.
        property int columns: Math.max(1, Math.floor((pane.width + gap) / ((wide ? 420 : 205) * pane.uiScale + gap)))
        property real cardWidth: Math.floor((pane.width + gap) / columns - gap)
        property real cardHeight: (wide ? 124 : 204) * pane.uiScale
        visible: pane.layout !== "list"
        width: columns * (cardWidth + gap); height: parent.height
        cellWidth: cardWidth + gap; cellHeight: cardHeight + gap
        clip: true; boundsBehavior: Flickable.StopAtBounds
        model: visible ? pane.items : []
        delegate: Item {
            width: grid.cellWidth; height: grid.cellHeight
            Rectangle {
                objectName: "contentCard"
                property bool lit: pane.lit(modelData)
                width: grid.cardWidth; height: grid.cardHeight; radius: 14 * pane.uiScale
                color: cardArea.pressed ? pane.tint(palette.highlightColor, 0.3)
                     : lit ? pane.tint(palette.highlightColor, 0.16) : pane.tint(palette.highlightBackgroundColor, 0.55)
                opacity: modelData.enabled ? 1 : 0.4
                Loader {
                    id: cardPicture
                    sourceComponent: picture
                    property real side: (grid.wide ? 100 : 112) * pane.uiScale
                    x: grid.wide ? 12 * pane.uiScale : (parent.width - side) / 2; y: 12 * pane.uiScale
                    width: side; height: side
                    onLoaded: { item.source = modelData.image || ""; item.label = pane.plain(modelData.title) }
                }
                Column {
                    x: grid.wide ? cardPicture.x + cardPicture.width + 14 * pane.uiScale : 10 * pane.uiScale
                    y: grid.wide ? 0 : cardPicture.y + cardPicture.height + 6 * pane.uiScale
                    width: parent.width - x - (grid.wide && (modelData.playback || modelData.kind === "folder") ? 50 : 10) * pane.uiScale
                    height: grid.wide ? parent.height : parent.height - y - 6 * pane.uiScale
                    Item { width: 1; height: grid.wide ? Math.max(0, (parent.height - cardTitle.height - cardSubtitle.height) / 2) : 0 }
                    Text {
                        id: cardTitle
                        width: parent.width; text: pane.plain(modelData.title); textFormat: Text.PlainText
                        color: lit ? palette.highlightColor : palette.primaryColor
                        font.pixelSize: 24 * pane.uiScale; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
                        horizontalAlignment: grid.wide ? Text.AlignLeft : Text.AlignHCenter
                    }
                    Text {
                        id: cardSubtitle
                        width: parent.width; height: visible ? implicitHeight : 0
                        visible: grid.wide && text !== ""
                        text: pane.plain(modelData.subtitle); textFormat: Text.PlainText
                        color: lit ? palette.secondaryHighlightColor : palette.secondaryColor
                        font.pixelSize: 20 * pane.uiScale; maximumLineCount: 1; elide: Text.ElideRight
                    }
                }
                Loader {
                    active: !!modelData.playback; sourceComponent: badge
                    anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8 * pane.uiScale
                    onLoaded: item.playback = modelData.playback
                }
                Image {
                    // A folder opens another page instead of starting something.
                    visible: modelData.kind === "folder" && !modelData.playback
                    anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6 * pane.uiScale
                    width: 34 * pane.uiScale; height: width
                    source: "image://theme/icon-m-right?" + palette.secondaryColor
                }
                MouseArea { id: cardArea; anchors.fill: parent; enabled: pane.usable && modelData.enabled; onClicked: pane.activated(modelData.id) }
            }
        }
        footer: Item {
            width: grid.width; height: pane.hasMore ? 74 * pane.uiScale : 0; visible: pane.hasMore
            Rectangle {
                width: parent.width - grid.gap; height: 62 * pane.uiScale; radius: 12 * pane.uiScale
                color: gridMoreArea.pressed ? pane.tint(palette.highlightColor, 0.3) : pane.tint(palette.highlightBackgroundColor, 0.55)
                Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Load more"); color: palette.highlightColor; font.pixelSize: 26 * pane.uiScale }
                MouseArea { id: gridMoreArea; anchors.fill: parent; enabled: pane.usable; onClicked: pane.moreRequested() }
            }
        }
    }
}
