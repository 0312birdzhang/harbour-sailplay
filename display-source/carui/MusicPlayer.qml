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
    property bool pendingPlayback: true
    readonly property bool systemPlayerInstalled: {
        var apps = carController.availableApps(true)
        for (var i=0; i<apps.length; ++i) if (apps[i].id === "jolla-mediaplayer") return true
        return false
    }
    readonly property bool systemPlayerRunning: !!carController.musicServiceForApp("jolla-mediaplayer", player.availableServices)
    property string selectedService: ""
    property bool playerMenuOpen: false
    property bool playRequestPending: false
    property string playbackError: ""
    function choosePlayer(service, resumePlaying) {
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
        onTriggered: if (player.currentService && (player.playbackStatus === Mpris.Playing || !carController.hasRememberedMusic))
            carController.rememberMusicPlayer(player.currentService)
    }
    function resumeMusic() {
        var service = selectedService || player.currentService || carController.preferredMusicService(player.availableServices)
        if (service) player.currentService = service
        if (service && (player.canPlay || carController.musicServiceForApp("jolla-mediaplayer",player.availableServices) === service)) {
            controls.playRequestPending = true
            carController.playMusicPlayer(service)
            return
        }
        selectPlayerApp(carController.lastMusicApp, true)
    }
    function selectPlayerApp(appId, play) {
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
            var service = carController.musicServiceForApp(controls.pendingApp, player.availableServices)
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
            if (controls.selectedService && player.availableServices.indexOf(controls.selectedService) >= 0) return
            controls.selectedService = ""
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
            var service = carController.musicServiceForApp(appId, player.availableServices)
            if (service && service === player.currentService) return
            if (service) controls.choosePlayer(service, true)
            else controls.selectPlayerApp(appId, controls.playing)
        }
        onPlayerPlaybackFinished: {
            if (service === player.currentService) controls.playRequestPending = false
        }
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
            text: controls.playbackError || carController.musicError || (controls.idleCard ? carController.lastMusicName : (player.metaData.contributingArtist || "").toString())
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
                              : player.playbackStatus === Mpris.Playing ? player.canPause : !pendingPlay.running && !controls.playRequestPending
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
    // Sized to be read and hit at a glance while driving: the application's
    // own icon identifies the player faster than its name.
    Rectangle {
        id: playerSelector
        objectName: "playerSelector"
        property int rowHeight: 84
        y: -(height + 16); width: parent.width; height: 76; radius: 14; color: carPalette.button
        visible: !controls.compact
        z: 20
        Image {
            id: selectorIcon
            objectName: "playerSelectorIcon"
            x: 12; anchors.verticalCenter: parent.verticalCenter
            width: 56; height: 56; fillMode: Image.PreserveAspectFit
            property string file: carController.musicAppIcon(player.desktopEntry || carController.lastMusicApp)
            source: file ? "file://" + file : ""
            visible: source != ""
        }
        Text {
            x: selectorIcon.visible ? 84 : 20; width: parent.width - x - 76; height: parent.height
            text: player.identity || carController.lastMusicName || qsTranslate("Sailplay", "Player")
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
            y: parent.height + 6; width: parent.width
            height: Math.min(4 * playerSelector.rowHeight, playerChoices.contentHeight)
            visible: controls.playerMenuOpen; radius: 14; color: carPalette.card
            border.color: carPalette.secondary
            ListView {
                id: playerChoices
                anchors.fill: parent; clip: true
                model: player.availableClients
                footer: Rectangle {
                    objectName: "systemPlayerChoice"
                    width: playerChoices.width
                    height: controls.systemPlayerInstalled && !controls.systemPlayerRunning ? playerSelector.rowHeight : 0
                    visible: height > 0
                    color: "transparent"
                    Image {
                        id: systemIcon
                        x: 12; anchors.verticalCenter: parent.verticalCenter
                        width: 60; height: 60; fillMode: Image.PreserveAspectFit
                        property string file: carController.musicAppIcon("jolla-mediaplayer")
                        source: file ? "file://" + file : ""
                        visible: source != ""
                    }
                    Text {
                        x: systemIcon.visible ? 88 : 20; width: parent.width - x - 16; height: parent.height
                        text: qsTranslate("Sailplay", "System Media")
                        elide: Text.ElideRight
                        color: carPalette.text; font.pixelSize: 30; verticalAlignment: Text.AlignVCenter
                    }
                    MouseArea { anchors.fill: parent; onClicked: controls.selectPlayerApp("jolla-mediaplayer", controls.playing) }
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
                        verticalAlignment: Text.AlignVCenter; color: carPalette.text; font.pixelSize: 30
                    }
                    Silica.Icon {
                        anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter
                        width: 40; height: 40; color: carPalette.text
                        source: "image://theme/icon-m-simple-play"
                        visible: modelData.playbackStatus === Mpris.Playing
                    }
                    MouseArea { anchors.fill: parent; enabled: !controls.playRequestPending; onClicked: controls.choosePlayer(modelData.service,true) }
                }
            }
        }
    }
}
