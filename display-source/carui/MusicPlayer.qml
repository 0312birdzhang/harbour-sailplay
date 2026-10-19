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
    readonly property real _squareSize: compact ? 72 : 88
    readonly property real headerHeight: compact ? 120 : 164
    signal clicked()
    height: headerHeight + 24 + _squareSize
    visible: true
    property string pendingApp: ""
    property int pendingTicks: 0
    Timer {
        id: rememberTimer; interval: 150
        onTriggered: if (player.currentService && (player.playbackStatus === Mpris.Playing || !carController.hasRememberedMusic))
            carController.rememberMusicPlayer(player.currentService)
    }
    Timer {
        id: pendingPlay; interval: 250; repeat: true
        onTriggered: {
            if (++controls.pendingTicks > 40) { stop(); controls.pendingApp = ""; return }
            var desktop = String(player.desktopEntry || "").replace(/\.desktop$/, "")
            if (desktop === controls.pendingApp && player.canPlay) {
                stop(); controls.pendingApp = ""; player.play()
            }
        }
    }
    Timer {
        id: selectPreferred; interval: 200
        onTriggered: {
            var clients = player.availableClients
            for (var i = 0; i < clients.length; ++i)
                if (clients[i].playbackStatus === Mpris.Playing) return
            var service = carController.preferredMusicService(player.availableServices)
            if (service) player.currentService = service
        }
    }
    Component.onCompleted: selectPreferred.restart()
    MprisController {
        id: player
        onAvailableServicesChanged: selectPreferred.restart()
        onCurrentServiceChanged: rememberTimer.restart()
        onDesktopEntryChanged: rememberTimer.restart()
        onPlaybackStatusChanged: if (playbackStatus === Mpris.Playing) rememberTimer.restart()
    }
    Rectangle {
        width: controls.compact ? 112 : 148; height: width; radius: 16; color: carPalette.button
        Image {
            anchors.fill: parent; anchors.margins: 4
            source: controls.albumArtSource
            fillMode: Image.PreserveAspectFit
        }
        Text { anchors.centerIn: parent; text: "♫"; color: carPalette.secondary; font.pixelSize: 64; visible: !controls.albumArtSource }
    }
    Column {
        x: controls.compact ? 132 : 172; width: Math.max(0, parent.width - x); spacing: controls.compact ? 6 : 12
        Text {
            width: parent.width; color: carPalette.text; font.pixelSize: controls.compact ? 28 : 34
            elide: Text.ElideRight
            text: player.metaData.title || player.identity || carController.lastMusicName
        }
        Text {
            width: parent.width; color: carPalette.secondary; font.pixelSize: 26
            elide: Text.ElideRight
            text: (player.metaData.contributingArtist || "").toString()
        }
        Text {
            width: parent.width; color: carPalette.secondary; font.pixelSize: 22
            elide: Text.ElideRight; text: player.identity || ""
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
                    enabled: index === 0 ? player.canGoPrevious : index === 2 ? player.canGoNext
                              : player.playbackStatus === Mpris.Playing ? player.canPause : (!player.currentService || player.canPlay)
                    opacity: enabled ? 1 : 0.35
                    icon.color: carPalette.text
                    icon.source: index === 0 ? "image://theme/icon-m-simple-previous"
                                 : index === 2 ? "image://theme/icon-m-simple-next"
                                 : player.playbackStatus === Mpris.Playing ? "image://theme/icon-m-simple-pause"
                                 : "image://theme/icon-m-simple-play"
                    onClicked: {
                        if (index === 0) player.previous()
                        else if (index === 2) player.next()
                        else if (player.currentService) player.playPause()
                        else {
                            controls.pendingApp = carController.lastMusicApp
                            controls.pendingTicks = 0
                            carController.startMusicOnPhone()
                            pendingPlay.restart()
                        }
                    }
                }
            }
        }
    }
}
