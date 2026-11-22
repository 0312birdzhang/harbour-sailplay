import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica
import Amber.Mpris 1.0

// Full-screen page of one music app. Unlike the dashboard card, which follows
// whatever is playing, this page stays on its own app's player: paused on its
// last track while another app plays.
Rectangle {
    id: page
    property var palette
    property string app: carController.musicPageApp
    property bool active: visible

    // Only the ambience roles of CarPalette are used here.
    color: palette.overlayBackgroundColor
    radius: 22
    clip: true

    readonly property bool wide: width > height * 1.25
    readonly property real margin: 40
    readonly property real artSide: wide ? Math.min(height - 2 * margin, width * 0.34)
                                         : Math.min(width - 2 * margin, height * 0.34)

    // --- The app's own MPRIS player -------------------------------------
    property string service: ""
    readonly property bool hasPlayer: service !== "" && player.currentService === service
    readonly property bool playing: hasPlayer && player.playbackStatus === Mpris.Playing
    readonly property string title: hasPlayer ? String(player.metaData.title || "") : ""
    readonly property string artist: hasPlayer ? String(player.metaData.contributingArtist || "") : ""
    readonly property string album: hasPlayer ? String(player.metaData.albumTitle || "") : ""

    function pin() {
        var wanted = app ? carController.musicServiceFor(app, player.availableServices) : ""
        service = wanted
        if (wanted && player.currentService !== wanted) player.currentService = wanted
    }
    onAppChanged: { pendingPlay.stop(); pin() }
    onActiveChanged: if (active) pin()
    Component.onCompleted: pin()
    Timer { id: repin; interval: 200; onTriggered: page.pin() }
    MprisController {
        id: player
        singleService: true
        onAvailableServicesChanged: repin.restart()
        onCurrentServiceChanged: if (page.service && currentService !== page.service) repin.restart()
    }

    property int pendingTicks: 0
    function play() {
        if (hasPlayer && player.canPlay) { player.play(); return }
        pendingTicks = 0
        if (carController.ensureMusicBackend(app)) pendingPlay.restart()
    }
    Timer {
        id: pendingPlay; interval: 250; repeat: true
        onTriggered: {
            if (++page.pendingTicks > 60) { stop(); return }
            page.pin()
            if (page.hasPlayer && player.canPlay) { stop(); player.play() }
        }
    }

    // --- Artwork ---------------------------------------------------------
    property string artworkKey: hasPlayer ? String(player.metaData.artUrl || player.metaData.url || "") : ""
    property url artwork: ""
    onArtworkKeyChanged: artwork = hasPlayer
        ? carController.artworkSource(player.metaData.artUrl || "", player.metaData.url || "") : ""
    Connections {
        target: carController
        onArtworkAvailable: if (key === page.artworkKey) page.artwork = localUrl
    }
    Rectangle {
        id: art
        x: page.wide ? page.margin : (page.width - width) / 2
        y: page.wide ? (page.height - height) / 2 : page.margin
        width: page.artSide; height: page.artSide; radius: 18
        color: palette.highlightBackgroundColor
        Image {
            anchors.centerIn: parent; width: parent.width * 0.4; height: width
            source: "image://theme/icon-l-music?" + palette.secondaryColor
            visible: cover.status !== Image.Ready
        }
        Image {
            id: cover
            anchors.fill: parent; anchors.margins: 4
            source: page.artwork; fillMode: Image.PreserveAspectCrop; asynchronous: true
        }
    }

    Item {
        id: info
        x: page.wide ? art.x + art.width + 56 : page.margin
        y: page.wide ? page.margin : art.y + art.height + 24
        width: page.width - x - page.margin
        height: page.height - y - page.margin

        // --- Which app this is, and its library --------------------------
        Item {
            id: header
            width: parent.width; height: 104
            Image {
                id: appIcon
                width: 88; height: 88; anchors.verticalCenter: parent.verticalCenter
                source: carController.musicPageIcon ? "file://" + carController.musicPageIcon : ""
                fillMode: Image.PreserveAspectFit
            }
            Text {
                x: appIcon.width + 24; anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, (browse.visible ? browse.x - 24 : parent.width) - x)
                text: carController.musicPageName
                textFormat: Text.PlainText; elide: Text.ElideRight
                color: palette.highlightColor; font.pixelSize: 40; font.weight: Font.Light
            }
            Rectangle {
                id: browse
                objectName: "musicBrowse"
                visible: carController.musicPageContentAvailable
                anchors.right: parent.right; width: Math.min(360, parent.width * 0.45); height: parent.height
                radius: 20
                color: browseTouch.pressed ? palette.highlightColor : palette.highlightBackgroundColor
                Row {
                    anchors.centerIn: parent; spacing: 18
                    Image {
                        width: 64; height: 64; anchors.verticalCenter: parent.verticalCenter
                        source: "image://theme/icon-m-events?"
                            + (browseTouch.pressed ? palette.overlayBackgroundColor : palette.primaryColor)
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTranslate("Sailplay", "Browse")
                        color: browseTouch.pressed ? palette.overlayBackgroundColor : palette.primaryColor
                        font.pixelSize: 38
                    }
                }
                MouseArea { id: browseTouch; anchors.fill: parent; onClicked: carController.browseMusic() }
            }
        }

        // --- Track --------------------------------------------------------
        Column {
            id: track
            width: parent.width; spacing: 10
            y: header.height + Math.max(16, (transport.y - header.height - height) / 2)
            Text {
                width: parent.width; textFormat: Text.PlainText
                text: page.title || (page.hasPlayer ? "" : qsTranslate("Sailplay", "Not Playing"))
                color: palette.primaryColor; font.pixelSize: 52; font.weight: Font.Light
                wrapMode: Text.WordWrap; maximumLineCount: page.wide && !line.text ? 2 : 1; elide: Text.ElideRight
            }
            Text {
                width: parent.width; textFormat: Text.PlainText
                text: page.hasPlayer ? page.artist : (carController.musicError || "")
                color: palette.secondaryHighlightColor; font.pixelSize: 36
                elide: Text.ElideRight; visible: text !== ""
            }
            Text {
                width: parent.width; textFormat: Text.PlainText
                text: page.album
                color: palette.secondaryColor; font.pixelSize: 30
                elide: Text.ElideRight; visible: text !== ""
            }
            Item { width: 1; height: 8 }

            // --- Position, queried from the player itself ------------------
            Item {
                id: progress
                width: parent.width; height: 100
                visible: page.hasPlayer
                // Amber metadata duration is milliseconds; queried MPRIS Position is microseconds.
                property real durationSeconds: page.hasPlayer ? Math.max(0, Number(player.metaData.duration || 0) / 1000) : 0
                property real positionSeconds: 0
                property string trackKey: page.hasPlayer ? [player.currentService || "", String(player.metaData.trackId || ""),
                    player.metaData.url || "", player.metaData.title || ""].join("|") : ""
                onTrackKeyChanged: { positionSeconds = 0; refresh() }
                property var seekTrackId
                property string seekService
                property bool dragging: seekTouch.pressed
                property real dragValue: 0
                readonly property real shown: dragging ? dragValue : Math.min(durationSeconds || positionSeconds, positionSeconds)
                readonly property bool seekable: page.hasPlayer && player.canSeek && durationSeconds > 0
                function timeText(seconds) {
                    var n = Math.max(0, Math.floor(seconds))
                    var hours = Math.floor(n / 3600), minutes = Math.floor(n % 3600 / 60)
                    return (hours ? hours + ":" + (minutes < 10 ? "0" : "") : "") + minutes
                        + ":" + (n % 60 < 10 ? "0" : "") + (n % 60)
                }
                function refresh() {
                    if (page.hasPlayer) carController.requestPlayerPosition(player.currentService, trackKey)
                    else positionSeconds = 0
                }
                Timer {
                    interval: 1000; repeat: true; triggeredOnStart: true
                    running: page.active && page.hasPlayer
                    onTriggered: progress.refresh()
                }
                Connections {
                    target: player
                    onPositionChanged: progress.refresh()
                    onPlaybackStatusChanged: progress.refresh()
                    onSeeked: progress.refresh()
                }
                Connections {
                    target: carController
                    onPlayerPositionAvailable: {
                        if (page.hasPlayer && service === player.currentService && trackKey === progress.trackKey)
                            progress.positionSeconds = Math.max(0, seconds)
                    }
                }
                Rectangle {
                    id: bar
                    y: 30; width: parent.width; height: 8; radius: 4
                    color: palette.highlightBackgroundColor
                    property real fraction: progress.durationSeconds > 0
                        ? Math.max(0, Math.min(1, progress.shown / progress.durationSeconds)) : 0
                    Rectangle { width: parent.width * parent.fraction; height: parent.height; radius: 4; color: palette.highlightColor }
                    Rectangle {
                        visible: progress.seekable
                        x: parent.width * parent.fraction - width / 2; anchors.verticalCenter: parent.verticalCenter
                        width: progress.dragging ? 40 : 28; height: width; radius: width / 2; color: palette.primaryColor
                    }
                }
                MouseArea {
                    id: seekTouch
                    width: parent.width; height: 68; enabled: progress.seekable
                    function valueAt(position) {
                        return Math.max(0, Math.min(1, position / width)) * progress.durationSeconds
                    }
                    onPressed: {
                        progress.seekTrackId = player.metaData.trackId
                        progress.seekService = player.currentService
                        progress.dragValue = valueAt(mouse.x)
                    }
                    onPositionChanged: progress.dragValue = valueAt(mouse.x)
                    onReleased: {
                        if (progress.seekService !== player.currentService) return
                        progress.positionSeconds = progress.dragValue
                        carController.seekPlayer(progress.seekService, progress.seekTrackId, Math.round(progress.dragValue))
                    }
                }
                Text {
                    y: 60; color: palette.secondaryColor; font.pixelSize: 30
                    text: progress.timeText(progress.shown)
                }
                Text {
                    y: 60; anchors.right: parent.right; color: palette.secondaryColor; font.pixelSize: 30
                    text: progress.durationSeconds > 0 ? progress.timeText(progress.durationSeconds) : "--:--"
                }
            }

            // --- Timed lyrics, when the player has them --------------------
            Item {
                id: lyrics
                width: parent.width; height: line.text ? 44 : 0; clip: true
                property var lines: []
                property int offsetMs: 0
                property string identity: progress.trackKey
                property int currentIndex: -1
                onIdentityChanged: { lines = []; currentIndex = -1; load() }
                function load() {
                    if (page.hasPlayer && player.metaData.trackId)
                        carController.requestPlayerLyrics(player.currentService, String(player.metaData.trackId), identity)
                }
                function update() {
                    var seconds = progress.positionSeconds + offsetMs / 1000
                    var i = -1
                    while (i + 1 < lines.length && lines[i + 1][0] <= seconds) ++i
                    currentIndex = i
                }
                Timer { interval: 5000; running: page.active && page.hasPlayer; repeat: true; triggeredOnStart: true; onTriggered: lyrics.load() }
                Connections { target: progress; onPositionSecondsChanged: lyrics.update() }
                Connections {
                    target: carController
                    onPlayerLyricsAvailable: {
                        if (key !== lyrics.identity) return
                        lyrics.lines = rows; lyrics.offsetMs = offsetMs; lyrics.update()
                    }
                }
                Text {
                    id: line
                    width: parent.width; horizontalAlignment: Text.AlignHCenter; textFormat: Text.PlainText
                    color: palette.primaryColor; font.pixelSize: 32; elide: Text.ElideRight
                    text: lyrics.currentIndex >= 0 && lyrics.currentIndex < lyrics.lines.length
                        ? lyrics.lines[lyrics.currentIndex][1] : ""
                }
            }
        }

        // --- Transport ----------------------------------------------------
        Row {
            id: transport
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height - height
            height: 132; spacing: Math.min(96, (parent.width - 3 * 132) / 2)
            Repeater {
                model: 3
                Rectangle {
                    width: 132; height: 132; radius: 66
                    property bool usable: index === 0 ? page.hasPlayer && player.canGoPrevious
                        : index === 2 ? page.hasPlayer && player.canGoNext
                        : page.playing ? player.canPause : !pendingPlay.running
                    color: touch.pressed ? palette.highlightBackgroundColor
                        : index === 1 ? palette.highlightBackgroundColor : "transparent"
                    opacity: usable ? 1 : 0.35
                    Image {
                        anchors.centerIn: parent
                        width: index === 1 ? 104 : 80; height: width
                        source: "image://theme/" + (index === 0 ? "icon-m-simple-previous"
                            : index === 2 ? "icon-m-simple-next"
                            : page.playing ? "icon-l-pause" : "icon-l-play")
                            + "?" + (touch.pressed ? palette.highlightColor : palette.primaryColor)
                    }
                    MouseArea {
                        id: touch
                        objectName: index === 1 ? "musicPlayPause" : ""
                        anchors.fill: parent; enabled: parent.usable
                        onClicked: {
                            if (index === 0) player.previous()
                            else if (index === 2) player.next()
                            else if (page.playing) player.pause()
                            else page.play()
                        }
                    }
                }
            }
        }
    }
}
