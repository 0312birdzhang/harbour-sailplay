import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica
import Amber.Mpris 1.0

// Both car layouts share one controller, never a projected player window.
Item {
    CarPalette { id: carPalette }
    id: controls
    property alias mprisController: player
    property url albumArtSource
    property bool compact: false
    readonly property bool playing: player.playbackStatus === Mpris.Playing
    readonly property bool idleCard: compact && !playing && player.playbackStatus !== Mpris.Paused
    readonly property real _squareSize: compact ? 72 : 88
    readonly property real coverSize: compact ? 112 : Math.min(220, width * .35)
    readonly property real headerHeight: compact ? 120 : Math.max(220, coverSize)
    signal clicked()
    height: headerHeight + 24 + _squareSize
    visible: true
    property string pendingApp: ""
    property int pendingTicks: 0
    property string selectedService: ""
    property bool playerMenuOpen: false
    function choosePlayer(service) {
        selectedService = service
        player.singleService = true
        player.currentService = service
        carController.rememberMusicPlayer(service)
        playerMenuOpen = false
    }
    Timer {
        id: rememberTimer; interval: 150
        onTriggered: if (player.currentService && (player.playbackStatus === Mpris.Playing || !carController.hasRememberedMusic))
            carController.rememberMusicPlayer(player.currentService)
    }
    function resumeMusic() {
        var service = selectedService || player.currentService || carController.preferredMusicService(player.availableServices)
        if (service) player.currentService = service
        if (service && player.canPlay) {
            player.play()
            return
        }
        controls.pendingApp = carController.lastMusicApp
        controls.pendingTicks = 0
        if (carController.ensureMusicBackend(controls.pendingApp))
            pendingPlay.restart()
    }
    Timer {
        id: pendingPlay; interval: 250; repeat: true
        onTriggered: {
            if (++controls.pendingTicks > 60) { stop(); controls.pendingApp = ""; return }
            var service = carController.preferredMusicService(player.availableServices)
            if (service) player.currentService = service
            var desktop = String(player.desktopEntry || "").replace(/\.desktop$/, "")
            if (desktop === controls.pendingApp && player.canPlay) {
                stop(); controls.pendingApp = ""; player.play()
            }
        }
    }
    Timer {
        id: selectPreferred; interval: 200
        onTriggered: {
            if (controls.selectedService && player.availableServices.indexOf(controls.selectedService) >= 0) return
            controls.selectedService = ""
            player.singleService = false
            var service = carController.preferredMusicService(player.availableServices)
            if (service) { player.currentService = service; return }
            var clients = player.availableClients
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
        onAvailableServicesChanged: selectPreferred.restart()
        onCurrentServiceChanged: rememberTimer.restart()
        onDesktopEntryChanged: rememberTimer.restart()
        onPlaybackStatusChanged: if (playbackStatus === Mpris.Playing) rememberTimer.restart()
    }
    Rectangle {
        width: controls.coverSize; height: width; radius: 16; color: carPalette.button
        Image {
            anchors.fill: parent; anchors.margins: 4
            source: controls.idleCard ? "" : controls.albumArtSource
            fillMode: Image.PreserveAspectFit
        }
        Text { anchors.centerIn: parent; text: "♫"; color: carPalette.secondary; font.pixelSize: 64; visible: controls.idleCard || !controls.albumArtSource }
    }
    Column {
        x: controls.coverSize + 20; width: Math.max(0, parent.width - x); spacing: controls.compact ? 6 : 12
        Text {
            width: parent.width; color: carPalette.text; font.pixelSize: controls.compact ? 28 : 34
            elide: Text.ElideRight
            text: controls.idleCard ? qsTranslate("Sailplay", "Not Playing")
                                  : player.metaData.title || player.identity || carController.lastMusicName
            textFormat: Text.PlainText
            wrapMode: controls.compact ? Text.NoWrap : Text.Wrap
            maximumLineCount: controls.compact ? 1 : 2
        }
        Text {
            width: parent.width; color: carPalette.secondary; font.pixelSize: 26
            elide: Text.ElideRight
            text: controls.idleCard ? (carController.musicError || carController.lastMusicName) : (player.metaData.contributingArtist || "").toString()
            textFormat: Text.PlainText
        }
        Text {
            width: parent.width; color: carPalette.secondary; font.pixelSize: 25
            visible: !controls.compact && !!text
            elide: Text.ElideRight; text: player.metaData.albumTitle || ""
            textFormat: Text.PlainText
        }
        Text {
            width: parent.width; color: carPalette.secondary; font.pixelSize: 22
            elide: Text.ElideRight; text: controls.idleCard ? "" : player.identity || ""
            textFormat: Text.PlainText
        }
    }
    MouseArea { width: parent.width; height: controls.headerHeight; onClicked: controls.clicked() }
    Row {
        y: controls.headerHeight + 24; width: parent.width
        Repeater {
            model: 3
            Item {
                width: controls.width / 3; height: controls._squareSize
                Silica.IconButton {
                    anchors.centerIn: parent; width: controls._squareSize; height: width
                    enabled: index === 0 ? (!controls.idleCard && player.canGoPrevious) : index === 2 ? (!controls.idleCard && player.canGoNext)
                              : player.playbackStatus === Mpris.Playing ? player.canPause : !pendingPlay.running
                    opacity: enabled ? 1 : 0.35
                    icon.color: carPalette.text
                    icon.source: index === 0 ? "image://theme/icon-m-simple-previous"
                                 : index === 2 ? "image://theme/icon-m-simple-next"
                                 : player.playbackStatus === Mpris.Playing ? "image://theme/icon-m-simple-pause"
                                 : "image://theme/icon-m-simple-play"
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
    Rectangle {
        id: playerSelector
        objectName: "playerSelector"
        y: -70; width: parent.width; height: 54; radius: 12; color: carPalette.button
        visible: !controls.compact
        z: 20
        Text {
            anchors.fill: parent; anchors.margins: 12
            text: (player.identity || carController.lastMusicName || qsTranslate("Sailplay", "Player")) + " ▾"
            textFormat: Text.PlainText; elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter; font.pixelSize: 24; color: carPalette.text
        }
        MouseArea { anchors.fill: parent; onClicked: controls.playerMenuOpen = !controls.playerMenuOpen }
        Rectangle {
            y: parent.height + 6; width: parent.width
            height: Math.min(300, playerChoices.contentHeight)
            visible: controls.playerMenuOpen; radius: 12; color: carPalette.card
            border.color: carPalette.secondary
            ListView {
                id: playerChoices
                anchors.fill: parent; clip: true
                model: player.availableClients
                delegate: Rectangle {
                    width: playerChoices.width; height: 64
                    color: modelData.service === player.currentService ? carPalette.button : "transparent"
                    Text {
                        anchors.fill: parent; anchors.margins: 12
                        text: modelData.identity + (modelData.playbackStatus === Mpris.Playing ? " ▶" : "")
                        textFormat: Text.PlainText; elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter; color: carPalette.text; font.pixelSize: 24
                    }
                    MouseArea { anchors.fill: parent; onClicked: controls.choosePlayer(modelData.service) }
                }
            }
        }
    }
}
