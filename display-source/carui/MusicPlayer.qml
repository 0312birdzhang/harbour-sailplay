import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica
import Amber.Mpris 1.0

// Both car layouts share one controller, never a projected player window.
Item {
    CarPalette { id: carPalette }
    id: controls
    property alias mprisController: player
    readonly property bool localCurrent: musicServices.indexOf(player.currentService) >= 0
    readonly property var localController: localCurrent ? player : null
    property url albumArtSource
    property bool compact: false
    property bool centered: false
    property real availableHeight: 0
    property Item playerSelectorHost: null
    readonly property bool playing: localCurrent && player.playbackStatus === Mpris.Playing
    // Read the selected player's state so changes in its own UI stay in sync.
    // 0: repeat track, 1: repeat list, 2: shuffle, 3: sequential.
    readonly property int playbackMode: !localCurrent ? 3
        : player.hasLoopStatus && player.loopStatus === Mpris.LoopTrack ? 0
        : player.hasShuffle && player.shuffle ? 2
        : player.hasLoopStatus && player.loopStatus === Mpris.LoopPlaylist ? 1 : 3
    readonly property string playbackModeText: playbackMode === 0 ? qsTranslate("Sailplay", "Repeat track")
        : playbackMode === 1 ? qsTranslate("Sailplay", "Repeat list")
        : playbackMode === 2 ? qsTranslate("Sailplay", "Shuffle") : qsTranslate("Sailplay", "Sequential")
    readonly property bool canCyclePlaybackMode: localCurrent && player.canControl && (player.hasLoopStatus || player.hasShuffle)
    function cyclePlaybackMode() {
        if (!canCyclePlaybackMode) return
        var mode = (playbackMode + 1) % 4
        // Some players implement only one of the optional MPRIS properties.
        while ((mode < 2 && !player.hasLoopStatus) || (mode === 2 && !player.hasShuffle))
            mode = (mode + 1) % 4
        if (player.hasShuffle) player.shuffle = mode === 2
        if (player.hasLoopStatus)
            player.loopStatus = mode === 0 ? Mpris.LoopTrack : mode === 3 ? Mpris.LoopNone : Mpris.LoopPlaylist
    }
    readonly property bool idleCard: compact && (!localCurrent || !playing && player.playbackStatus !== Mpris.Paused)
    readonly property real _squareSize: centered ? Math.max(0, Math.min(compact ? 88 : 100, width / 4 - 8)) : compact ? 76 : 88
    readonly property real controlGap: centered ? 12 : 24
    readonly property real trackGap: 12
    readonly property real coverSize: centered ? Math.max(0, Math.min(compact ? 208 : 340, width,
        availableHeight - trackInfo.height - trackGap - controlGap - _squareSize)) : compact ? 112 : Math.min(220, width * .35)
    readonly property real headerHeight: centered ? trackInfo.y + trackInfo.height : compact ? 120 : Math.max(220, coverSize)
    signal clicked()
    height: headerHeight + controlGap + _squareSize
    visible: true
    property string pendingApp: ""
    property int pendingTicks: 0
    property bool pendingPlayback: true
    readonly property var musicServices: player.availableServices.filter(function(service) {
        return carController.isLocalMusicService(service)
    })
    readonly property var musicClients: player.availableClients.filter(function(client) {
        return controls.musicServices.indexOf(client.service) >= 0
    })
    readonly property var stoppedPlayers: {
        var apps = carController.availableApps(true)
        var result = []
        for (var i=0; i<apps.length; ++i) {
            if (apps[i].backgroundPlayer && !carController.musicServiceForApp(apps[i].id, controls.musicServices))
                result.push(apps[i])
        }
        return result
    }
    property string selectedService: ""
    property bool playerMenuOpen: false
    property bool playRequestPending: false
    property string playbackError: ""
    function cancelPendingPlayer() {
        pendingPlay.stop()
        controls.pendingApp = ""
        controls.pendingTicks = 0
    }
    function choosePlayer(service, resumePlaying) {
        if (controls.musicServices.indexOf(service) < 0) return
        cancelPendingPlayer()
        var resume = resumePlaying === true && controls.playing && player.currentService !== service
        selectedService = service
        player.singleService = true
        player.currentService = service
        carController.rememberMusicPlayer(service)
        playerMenuOpen = false
        playbackError = ""
        if (resume) resumeMusic()
    }
    Timer {
        id: rememberTimer; interval: 150
        onTriggered: if (controls.musicServices.indexOf(player.currentService) >= 0 && (player.playbackStatus === Mpris.Playing || !carController.hasRememberedMusic))
            carController.rememberMusicPlayer(player.currentService)
    }
    function resumeMusic() {
        var service = selectedService || player.currentService
        if (controls.musicServices.indexOf(service) < 0) service = carController.preferredMusicService(controls.musicServices)
        if (service) player.currentService = service
        if (service && (player.canPlay || carController.musicServiceForApp("jolla-mediaplayer",controls.musicServices) === service)) {
            controls.playRequestPending = true
            carController.playMusicPlayer(service)
            return
        }
        selectPlayerApp(carController.lastMusicApp, true)
    }
    function selectPlayerApp(appId, play) {
        cancelPendingPlayer()
        controls.pendingApp = appId
        controls.pendingPlayback = play
        controls.pendingTicks = 0
        controls.playerMenuOpen = false
        if (carController.ensureMusicBackend(controls.pendingApp))
            pendingPlay.restart()
    }
    Timer {
        id: pendingPlay; interval: 250; repeat: true
        onTriggered: {
            if (++controls.pendingTicks > 60) { stop(); controls.pendingApp = ""; return }
            var service = carController.musicServiceForApp(controls.pendingApp, controls.musicServices)
            if (service) player.currentService = service
            if (service) {
                stop(); controls.pendingApp = ""; controls.choosePlayer(service)
                if (controls.pendingPlayback) controls.resumeMusic()
            }
        }
    }
    Timer {
        id: selectPreferred; interval: 200
        onTriggered: {
            if (controls.selectedService && controls.musicServices.indexOf(controls.selectedService) >= 0) return
            controls.selectedService = ""
            var service = carController.preferredMusicService(controls.musicServices)
            if (service) { player.currentService = service; return }
            var clients = controls.musicClients
            for (var i = 0; i < clients.length; ++i)
                if (clients[i].playbackStatus === Mpris.Playing) { player.currentService = clients[i].service; return }
            if (clients.length) player.currentService = clients[0].service
        }
    }
    Component.onCompleted: {
        selectPreferred.restart()
        // Prepare the remembered background service, but Play is sent by the
        // transport only after the head unit's audio channel is ready.
        carController.ensureMusicBackend()
    }
    MprisController {
        id: player
        // Amber can dereference a removed client when switching back to
        // automatic selection. Keep explicit selection throughout its life.
        singleService: true
        onAvailableServicesChanged: selectPreferred.restart()
        onCurrentServiceChanged: rememberTimer.restart()
        onDesktopEntryChanged: rememberTimer.restart()
        onPlaybackStatusChanged: if (playbackStatus === Mpris.Playing) rememberTimer.restart()
    }
    Connections {
        target: carController
        // Tapping a music app's icon selects that app's player, as its row in
        // the player menu does, instead of showing whichever was selected.
        onMusicAppRequested: {
            controls.cancelPendingPlayer()
            var service = carController.musicServiceForApp(appId, controls.musicServices)
            if (service && service === player.currentService) return
            if (service) controls.choosePlayer(service, true)
            else controls.selectPlayerApp(appId, controls.playing)
        }
        onPlayerPlaybackFinished: {
            if (service === player.currentService) controls.playRequestPending = false
        }
    }
    Rectangle {
        objectName: "musicArtwork"
        x: controls.centered ? (parent.width - width) / 2 : 0
        width: controls.coverSize; height: width; radius: 16; color: carPalette.button
        Image {
            anchors.fill: parent; anchors.margins: 4
            source: controls.idleCard || !controls.localCurrent ? "" : controls.albumArtSource
            fillMode: Image.PreserveAspectFit
        }
        Text { anchors.centerIn: parent; text: "♫"; color: carPalette.secondary; font.pixelSize: controls.centered ? Math.max(1, parent.width * .36) : 64; visible: controls.idleCard || !controls.albumArtSource }
    }
    Column {
        id: trackInfo
        objectName: "musicTrackInfo"
        x: controls.centered ? 0 : controls.coverSize + 20
        y: controls.centered ? controls.coverSize + controls.trackGap : 0
        width: Math.max(0, parent.width - x); spacing: controls.centered || controls.compact ? 6 : 12
        readonly property string artist: controls.localCurrent ? (player.metaData.contributingArtist || "").toString() : ""
        readonly property string album: controls.localCurrent ? player.metaData.albumTitle || "" : ""
        Text {
            width: parent.width; color: carPalette.text
            horizontalAlignment: controls.centered ? Text.AlignHCenter : Text.AlignLeft
            font.pixelSize: controls.centered ? (controls.compact ? 34 : 44) : (controls.compact ? 28 : 34)
            elide: Text.ElideRight
            text: controls.idleCard ? qsTranslate("Sailplay", "Not Playing")
                                  : controls.localCurrent ? player.metaData.title || player.identity || carController.lastMusicName : carController.lastMusicName
            textFormat: Text.PlainText
            wrapMode: controls.centered || controls.compact ? Text.NoWrap : Text.Wrap
            maximumLineCount: controls.centered || controls.compact ? 1 : 2
        }
        Text {
            width: parent.width; color: carPalette.secondary
            horizontalAlignment: controls.centered ? Text.AlignHCenter : Text.AlignLeft
            font.pixelSize: controls.centered ? (controls.compact ? 27 : 30) : 26
            elide: Text.ElideRight
            text: controls.playbackError || carController.musicError || (controls.idleCard ? carController.lastMusicName
                : controls.centered && trackInfo.album ? (trackInfo.artist ? trackInfo.artist + " · " + trackInfo.album : trackInfo.album)
                : trackInfo.artist)
            textFormat: Text.PlainText
            visible: !controls.centered || !!text
        }
        Text {
            width: parent.width; color: carPalette.secondary; font.pixelSize: 25
            visible: !controls.centered && !controls.compact && !!text
            elide: Text.ElideRight; text: trackInfo.album
            textFormat: Text.PlainText
        }
        Text {
            width: parent.width; color: carPalette.secondary; font.pixelSize: 22
            visible: !controls.centered
            elide: Text.ElideRight; text: controls.idleCard || !controls.localCurrent ? "" : player.identity || ""
            textFormat: Text.PlainText
        }
    }
    MouseArea { width: parent.width; height: controls.headerHeight; onClicked: controls.clicked() }
    Row {
        y: controls.headerHeight + controls.controlGap; width: parent.width
        Repeater {
            model: 3
            Item {
                width: controls.width / 4; height: controls._squareSize
                Rectangle {
                    anchors.centerIn: parent; width: controls._squareSize; height: width
                    radius: 14
                    color: transportTouch.pressed ? carPalette.pressed : carPalette.button
                    enabled: index === 0 ? (controls.localCurrent && !controls.idleCard && player.canGoPrevious) : index === 2 ? (controls.localCurrent && !controls.idleCard && player.canGoNext)
                              : controls.playing ? player.canPause : !pendingPlay.running && !controls.playRequestPending
                    opacity: enabled ? 1 : 0.35
                    Silica.Icon {
                        anchors.centerIn: parent
                        width: Math.min(controls._squareSize * .65, controls.centered ? 60 : controls.compact ? 44 : 52); height: width
                        color: transportTouch.pressed ? carPalette.highlightColor : carPalette.text
                        source: index === 0 ? "image://theme/icon-m-simple-previous"
                              : index === 2 ? "image://theme/icon-m-simple-next"
                              : controls.playing ? "image://theme/icon-m-simple-pause"
                              : "image://theme/icon-m-simple-play"
                    }
                    MouseArea {
                        id: transportTouch
                        anchors.fill: parent
                        onClicked: {
                            if (index === 0) player.previous()
                            else if (index === 2) player.next()
                            else if (controls.playing) player.pause()
                            else controls.resumeMusic()
                        }
                    }
                }
            }
        }
        Item {
            width: controls.width / 4; height: controls._squareSize
            Rectangle {
                objectName: "playbackModeButton"
                anchors.centerIn: parent
                width: controls._squareSize; height: width
                radius: 14
                color: playbackModeTouch.pressed ? carPalette.pressed : carPalette.button
                enabled: controls.canCyclePlaybackMode
                opacity: enabled ? 1 : 0.35
                Canvas {
                    anchors.centerIn: parent
                    width: Math.min(controls._squareSize * .65, controls.centered ? 60 : controls.compact ? 44 : 52); height: width
                    property int mode: controls.playbackMode
                    property color ink: carPalette.text
                    onModeChanged: requestPaint()
                    onInkChanged: requestPaint()
                    onPaint: {
                        var c = getContext("2d")
                        c.clearRect(0, 0, width, height)
                        c.save(); c.scale(width / 48, height / 48)
                        c.strokeStyle = ink; c.fillStyle = ink; c.lineWidth = 3
                        c.lineCap = "round"; c.lineJoin = "round"
                        function line(points) {
                            c.beginPath(); c.moveTo(points[0], points[1])
                            for (var i = 2; i < points.length; i += 2) c.lineTo(points[i], points[i+1])
                            c.stroke()
                        }
                        if (mode === 2) {
                            line([6,12,13,12,35,36,42,36]); line([36,30,42,36,36,42])
                            line([6,36,13,36,35,12,42,12]); line([36,6,42,12,36,18])
                        } else if (mode === 3) {
                            line([7,10,31,10]); line([7,22,31,22]); line([7,34,42,34])
                            line([36,28,42,34,36,40])
                        } else {
                            line([7,24,7,14,12,9,40,9]); line([34,3,40,9,34,15])
                            line([41,24,41,34,36,39,8,39]); line([14,33,8,39,14,45])
                        }
                        c.restore()
                    }
                    Text {
                        anchors.centerIn: parent; visible: controls.playbackMode === 0
                        text: "1"; color: carPalette.text; font.pixelSize: 22; font.bold: true
                    }
                }
                MouseArea {
                    id: playbackModeTouch
                    objectName: "playbackModeTouch"
                    anchors.fill: parent
                    onClicked: controls.cyclePlaybackMode()
                }
            }
        }
    }
    // Sized to be read and hit at a glance while driving: the application's
    // own icon identifies the player faster than its name.
    Rectangle {
        id: playerSelector
        objectName: "playerSelector"
        property int rowHeight: 84
        parent: controls.playerSelectorHost || controls
        y: controls.playerSelectorHost ? 0 : -(height + 16)
        width: parent.width; height: 76; radius: 14; color: carPalette.button
        visible: !controls.compact
        z: 20
        Image {
            id: selectorIcon
            objectName: "playerSelectorIcon"
            x: 12; anchors.verticalCenter: parent.verticalCenter
            width: 56; height: 56; fillMode: Image.PreserveAspectFit
            property string file: carController.musicAppIcon((controls.localCurrent ? player.desktopEntry : "") || carController.lastMusicApp)
            source: file ? "file://" + file : ""
            visible: source != ""
        }
        Text {
            x: selectorIcon.visible ? 84 : 20; width: parent.width - x - 76; height: parent.height
            text: (controls.localCurrent ? player.identity : "") || carController.lastMusicName || qsTranslate("Sailplay", "Player")
            textFormat: Text.PlainText; elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter; font.pixelSize: 30; color: carPalette.text
        }
        Silica.Icon {
            anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter
            width: 44; height: 44; color: carPalette.text
            source: controls.playerMenuOpen ? "image://theme/icon-m-up" : "image://theme/icon-m-down"
        }
        MouseArea { anchors.fill: parent; onClicked: controls.playerMenuOpen = !controls.playerMenuOpen }
        Rectangle {
            objectName: "playerMenu"
            y: parent.height + 6; width: parent.width
            height: Math.min(4 * playerSelector.rowHeight, playerChoices.contentHeight)
            visible: controls.playerMenuOpen; radius: 14; color: carPalette.card
            border.color: carPalette.secondary
            ListView {
                id: playerChoices
                anchors.fill: parent; clip: true
                model: controls.musicClients
                footer: Column {
                    width: playerChoices.width
                    Repeater {
                        model: controls.stoppedPlayers
                        Rectangle {
                            objectName: "stoppedPlayerChoice_" + modelData.id
                            width: playerChoices.width
                            height: playerSelector.rowHeight
                            color: "transparent"
                            Image {
                                id: systemIcon
                                x: 12; anchors.verticalCenter: parent.verticalCenter
                                width: 60; height: 60; fillMode: Image.PreserveAspectFit
                                property string file: modelData.icon || carController.musicAppIcon(modelData.id)
                                source: file ? "file://" + file : ""
                                visible: source != ""
                            }
                            Text {
                                x: systemIcon.visible ? 88 : 20; width: parent.width - x - 16; height: parent.height
                                text: modelData.id === "jolla-mediaplayer" ? qsTranslate("Sailplay", "System Media") : modelData.name
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: carPalette.text; font.pixelSize: 30; verticalAlignment: Text.AlignVCenter
                            }
                            MouseArea {
                                objectName: "stoppedPlayerTouch_" + modelData.id
                                anchors.fill: parent
                                enabled: !controls.playRequestPending
                                onClicked: controls.selectPlayerApp(modelData.id, controls.playing)
                            }
                        }
                    }
                }
                delegate: Rectangle {
                    width: playerChoices.width; height: playerSelector.rowHeight
                    color: modelData.service === player.currentService ? carPalette.button : "transparent"
                    Image {
                        id: choiceIcon
                        x: 12; anchors.verticalCenter: parent.verticalCenter
                        width: 60; height: 60; fillMode: Image.PreserveAspectFit
                        property string file: carController.musicAppIcon(modelData.desktopEntry || "")
                        source: file ? "file://" + file : ""
                        visible: source != ""
                    }
                    Text {
                        x: choiceIcon.visible ? 88 : 20; width: parent.width - x - 72; height: parent.height
                        text: modelData.identity
                        textFormat: Text.PlainText; elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter; font.pixelSize: 30
                        color: modelData.service === player.currentService ? carPalette.highlightColor : carPalette.text
                    }
                    Silica.Icon {
                        anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter
                        width: 40; height: 40; color: carPalette.highlightColor
                        source: "image://theme/icon-m-simple-play"
                        visible: modelData.playbackStatus === Mpris.Playing
                    }
                    MouseArea { anchors.fill: parent; enabled: !controls.playRequestPending; onClicked: controls.choosePlayer(modelData.service,true) }
                }
            }
        }
    }
}
