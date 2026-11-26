import QtQuick 2.0

Item {
    id: panel
    objectName: "musicLyrics"
    property var palette
    property var player
    property string trackKey
    property real positionSeconds: 0
    property bool expanded: false
    property var lines: []
    property string plainText: ""
    property bool loading: false
    property bool requested: false
    property int offsetMs: 0
    property int currentIndex: -1
    readonly property int compactStart: Math.max(0, Math.min(currentIndex - 1, lines.length - 4))
    readonly property var compactLines: lines.slice(compactStart, compactStart + 4)
    readonly property real compactRowHeight: Math.min(44, Math.max(0, (height - 24) / 4))
    clip: true
    onTrackKeyChanged: { lines = []; plainText = ""; currentIndex = -1; requested = false; load() }
    onPositionSecondsChanged: update()
    function load() {
        if (!player || !player.currentService || !carController.playerTrackId(player.metaData.trackId)) {
            loading = false
            return
        }
        // Background refresh must not flash the initial loading placeholder.
        loading = !requested
        carController.requestPlayerLyrics(player.currentService, player.metaData.trackId, trackKey)
    }
    function update() {
        var seconds = positionSeconds + offsetMs / 1000
        var i = -1
        while (i + 1 < lines.length && lines[i + 1][0] <= seconds) ++i
        currentIndex = lines.length ? Math.max(0, i) : -1
    }
    Timer { interval: 5000; running: panel.visible; repeat: true; triggeredOnStart: true; onTriggered: panel.load() }
    Connections {
        target: carController
        onPlayerLyricsAvailable: {
            if (key !== panel.trackKey) return
            panel.loading = false
            panel.requested = true
            panel.lines = rows.filter(function(row) { return String(row[1]).trim().length > 0 })
            panel.offsetMs = offsetMs
            panel.plainText = plainText
            panel.update()
        }
    }
    ListView {
        id: timedLines
        objectName: "timedLyrics"
        anchors.fill: parent
        visible: panel.expanded && panel.lines.length > 0
        model: panel.lines
        currentIndex: panel.currentIndex
        interactive: false
        spacing: panel.expanded ? 18 : 8
        preferredHighlightBegin: panel.expanded ? height * .40 : Math.min(44, height * .30)
        preferredHighlightEnd: preferredHighlightBegin
        highlightRangeMode: ListView.StrictlyEnforceRange
        highlightMoveDuration: 180
        delegate: Text {
            objectName: "lyricLine_" + index
            width: timedLines.width
            text: modelData[1]
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            font.pixelSize: panel.expanded ? (index === panel.currentIndex ? 36 : 28) : 25
            font.bold: index === panel.currentIndex
            color: index === panel.currentIndex ? panel.palette.highlightColor : panel.palette.secondary
            opacity: index === panel.currentIndex ? 1 : .65
        }
    }
    Column {
        objectName: "compactLyrics"
        width: parent.width
        height: compactRows.count * panel.compactRowHeight
        anchors.verticalCenter: parent.verticalCenter
        visible: !panel.expanded && panel.lines.length > 0
        Repeater {
            id: compactRows
            model: panel.compactLines
            Text {
                objectName: "compactLyricLine_" + index
                width: panel.width; height: panel.compactRowHeight
                text: String(modelData[1]).replace(/\s*\n\s*/g, " ")
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                font.pixelSize: Math.min(25, panel.compactRowHeight * .8)
                font.bold: panel.compactStart + index === panel.currentIndex
                color: font.bold ? panel.palette.text : panel.palette.secondary
                opacity: font.bold ? 1 : .65
            }
        }
    }
    Flickable {
        anchors.fill: parent
        visible: panel.expanded && !panel.lines.length && !!panel.plainText
        contentHeight: plainLyrics.height
        Text {
            id: plainLyrics
            width: parent.width
            text: panel.plainText; textFormat: Text.PlainText
            wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter
            font.pixelSize: panel.expanded ? 30 : 25; color: panel.palette.text
        }
    }
    Text {
        objectName: "compactPlainLyrics"
        width: parent.width
        anchors.verticalCenter: parent.verticalCenter
        visible: !panel.expanded && !panel.lines.length && !!panel.plainText
        text: panel.plainText; textFormat: Text.PlainText
        wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight
        horizontalAlignment: Text.AlignHCenter
        font.pixelSize: Math.min(25, panel.compactRowHeight * .8)
        color: panel.palette.text
    }
    Text {
        anchors.centerIn: parent; width: parent.width
        visible: !panel.lines.length && !panel.plainText
        text: panel.loading ? qsTranslate("Sailplay", "Loading lyrics…") : qsTranslate("Sailplay", "No lyrics available")
        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
        color: panel.palette.secondary; font.pixelSize: panel.expanded ? 28 : 22
    }
}
