import QtQuick 2.0
import QtQuick.Window 2.0
import Sailfish.Silica 1.0 as Silica

Window {
    id: projectionWindow
    visible: true; width: Number(Qt.application.arguments[2] || 1920); height: Number(Qt.application.arguments[3] || 720); color: carPalette.gradientMiddle
    Component.onCompleted: carController.restoreShellView()
    title: "Sailife UI" // Compositor fullscreen-shell identifier.
    Item {
    CarPalette { id: carPalette }
    id: root
    property bool portrait: projectionWindow.height > projectionWindow.width
    width: projectionWindow.width / scale; height: projectionWindow.height / scale
    scale: Math.min(projectionWindow.width / (portrait ? 900 : 1920), projectionWindow.height / 720)
    transformOrigin: Item.TopLeft
    property string clockText: Qt.formatDateTime(new Date(), "hh:mm")
    property var status: carController.status
    property var apps: carController.tiles
    property int gridColumns: Math.max(1, Math.min(6, Math.floor((width - dock.width - 64) / 350)))
    property int gridRows: Math.max(1, Math.min(4, Math.floor((height - 114) / 270)))
    property int pageSize: gridColumns * gridRows
    property int pageCount: Math.max(1, Math.ceil((apps.length + 1) / pageSize))
    onPageCountChanged: if (pages.currentIndex >= pageCount) pages.goToPage(pageCount - 1)
    property int battery: status.battery === undefined ? -1 : status.battery
    property int mobile: status.mobileStrength === undefined ? -1 : status.mobileStrength
    property string notice: ""
    Timer { id: noticeTimer; interval: 5000; onTriggered: root.notice = "" }
    Timer { interval: 15000; running: true; repeat: true; onTriggered: root.clockText = Qt.formatDateTime(new Date(), "hh:mm") }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: carPalette.gradientTop }
            GradientStop { position: 0.55; color: carPalette.gradientMiddle }
            GradientStop { position: 1; color: carPalette.gradientBottom }
        }
    }
    Rectangle {
        id: dock
        width: Math.round(140 * root.scale) / root.scale; height: parent.height; color: carPalette.dock
        Text { y: 25; anchors.horizontalCenter: parent.horizontalCenter; text: root.clockText; color: carPalette.text; font.pixelSize: 37; font.bold: true }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter; y: 83; spacing: 7
            Row {
                visible: root.status.mobileSupported === true; spacing: 3; height: 24
                Repeater {
                    model: 4
                    Rectangle {
                        width: 7; height: 7 + index * 5; anchors.bottom: parent.bottom; radius: 1
                        color: root.mobile >= (index + 1) * 25 ? carPalette.text : carPalette.disabled
                    }
                }
            }
            Text { visible: root.status.mobileSupported === true; width: 33; text: root.mobile < 0 ? "—" : (root.status.mobileType || ""); color: carPalette.text; font.pixelSize: 18; anchors.verticalCenter: parent.verticalCenter }
            Canvas {
                width: 32; height: 27
                property int strength: root.status.wifiConnected ? root.status.wifiStrength : -1
                onStrengthChanged: requestPaint()
                property color ink: carPalette.text
                property color dim: carPalette.disabled
                onInkChanged: requestPaint()
                onDimChanged: requestPaint()
                onPaint: {
                    var c = getContext("2d"); c.clearRect(0, 0, width, height); c.lineWidth = 3; c.lineCap = "round"
                    for (var i = 0; i < 3; i++) {
                        c.strokeStyle = strength >= (i * 33 + 1) ? carPalette.text : carPalette.disabled
                        c.beginPath(); c.arc(16, 25, 6 + i * 7, Math.PI * 1.24, Math.PI * 1.76); c.stroke()
                    }
                    c.fillStyle = strength >= 0 ? carPalette.text : carPalette.disabled; c.beginPath(); c.arc(16, 24, 2, 0, Math.PI * 2); c.fill()
                }
            }
        }
        Row {
            y: 127; anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
            Rectangle {
                width: 38; height: 20; radius: 4; color: "transparent"; border.width: 2; border.color: root.battery >= 0 ? carPalette.text : carPalette.disabled
                Rectangle { x: 4; y: 4; height: 12; width: Math.max(0, 30 * root.battery / 100); radius: 1; color: root.status.charging ? "#55dc83" : root.battery <= 20 ? "#ff675c" : carPalette.text }
                Rectangle { x: 39; y: 6; width: 3; height: 8; radius: 1; color: carPalette.batteryCap }
                Text { anchors.centerIn: parent; text: root.status.charging ? "ϟ" : ""; color: "#14251a"; font.pixelSize: 20 }
            }
            Text { text: root.battery < 0 ? "—" : root.battery + "%"; color: carPalette.text; font.pixelSize: 18 }
        }
        Repeater {
            model: carController.dockApps.slice(0, 3)
            Rectangle {
                x: 25; y: 207 + index * 121; width: 90; height: 90; radius: 21; color: dockTouch.pressed ? carPalette.pressed : carPalette.card
                Image { anchors.centerIn: parent; width: 78; height: 78; fillMode: Image.PreserveAspectFit; source: modelData.icon ? "file://" + modelData.icon : ""; visible: source !== "" }
                Text { anchors.centerIn: parent; text: modelData.icon ? "" : modelData.name.charAt(0); color: carPalette.text; font.pixelSize: 38 }
                MouseArea { id: dockTouch; anchors.fill: parent; onClicked: carController.dockClicked(modelData.appId) }
            }
        }
        Rectangle {
            x: 25; y: parent.height - 108; width: 90; height: 86; radius: 22; color: homeTouch.pressed ? carPalette.pressed : "transparent"
            Grid { id: homeGrid; visible: carController.dashboardActive || (!carController.returnToDashboard && (carController.musicActive || carController.currentApp !== "")); anchors.centerIn: parent; columns: 3; spacing: 5; Repeater { model: 9; Rectangle { width: 11; height: 11; radius: 3; color: carPalette.text } } }
            Text { visible: !homeGrid.visible; anchors.centerIn: parent; text: "◫"; color: carPalette.text; font.pixelSize: 42 }
            MouseArea { id: homeTouch; anchors.fill: parent; onClicked: carController.homeClicked() }
        }
    }
    Silica.SlideshowView {
        id: pages
        visible: carController.currentApp === "" && !carController.dashboardActive && !carController.musicActive
        x: dock.width; width: root.width - x; height: root.height - 66
        itemWidth: width; itemHeight: height
        orientation: Qt.Horizontal
        function goToPage(page) {
            currentIndex = Math.max(0, Math.min(root.pageCount - 1, page))
        }
        clip: true; model: root.pageCount
        delegate: Item {
            width: pages.width; height: pages.height
            property int pageIndex: index
            Grid {
                anchors.centerIn: parent
                columns: root.gridColumns
                property real cellWidth: (pages.width - 64) / columns
                property real cellHeight: Math.min(330, (pages.height - 48) / root.gridRows)
                Repeater {
                    model: root.pageSize
                    Item {
                        property int appIndex: parent.parent.pageIndex * root.pageSize + index - 1
                        property bool oem: appIndex === -1
                        property var entry: appIndex >= 0 && appIndex < root.apps.length ? root.apps[appIndex] : null
                        visible: oem || entry !== null
                        width: parent.cellWidth; height: parent.cellHeight
                        property real iconSize: Math.min(156, width * 0.55, height * 0.55)
                        property real labelSize: Math.min(31, iconSize * 0.23)
                        property real labelGap: iconSize * 0.12
                        property real tileTop: (height - iconSize - labelGap - labelSize * 1.3) / 2
                        Rectangle {
                            y: parent.tileTop; anchors.horizontalCenter: parent.horizontalCenter
                            width: parent.iconSize; height: width; radius: width * 34 / 156; color: oem ? carPalette.oem : carPalette.tile; opacity: appTouch.pressed ? 0.65 : 1
                            Image { anchors.fill: parent; anchors.margins: 8; fillMode: Image.PreserveAspectFit; source: entry && entry.icon ? "file://" + entry.icon : ""; visible: !oem && source !== "" }
                            Text { anchors.centerIn: parent; visible: !oem && entry && !entry.icon; text: entry ? entry.name.charAt(0) : ""; font.pixelSize: parent.width * 76 / 156; color: carPalette.text }
                            Canvas {
                                anchors.centerIn: parent; width: 112; height: 98; visible: oem
                                scale: parent.width / 156
                                property color ink: carPalette.text
                                onInkChanged: requestPaint()
                                onPaint: {
                                    var c = getContext("2d"); c.lineWidth = 5; c.strokeStyle = carPalette.text; c.lineJoin = "round"
                                    c.beginPath(); c.moveTo(15, 45); c.lineTo(29, 17); c.lineTo(83, 17); c.lineTo(97, 45); c.closePath(); c.stroke()
                                    c.strokeRect(12, 45, 88, 34); c.fillStyle = carPalette.text
                                    c.fillRect(17, 55, 15, 6); c.fillRect(80, 55, 15, 6); c.fillRect(18, 80, 12, 12); c.fillRect(82, 80, 12, 12)
                                }
                            }
                        }
                        Text { y: parent.tileTop + parent.iconSize + parent.labelGap; width: parent.width - 20; anchors.horizontalCenter: parent.horizontalCenter; text: oem ? qsTranslate("Sailplay", "Return to car") : entry ? entry.name : ""; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; font.pixelSize: parent.labelSize; color: carPalette.text }
                        MouseArea {
                            id: appTouch; anchors.fill: parent
                            onClicked: {
                                if (oem) {
                                    carController.returnToCar()

                                } else carController.tileClicked(appIndex)
                            }
                        }
                    }
                }
            }
        }
    }
    Item {
        visible: carController.dashboardActive || carController.musicActive
        x: dock.width; width: root.width - x; height: root.height
        // Horizontal design units scale with width; vertical spacing follows height.
        property real verticalGap: height * 16 / 720
        property real mapWidth: (width - 48) * 0.65
        Loader {
            id: weatherCard
            visible: !carController.musicActive
            x: parent.mapWidth + 32; y: parent.verticalGap
            width: parent.width - parent.mapWidth - 48
            height: (parent.height - 3 * parent.verticalGap) * 0.35
            source: "WeatherCard.qml"
        }
        Rectangle {
            visible: !carController.musicActive
            x: 16; y: parent.verticalGap; width: parent.mapWidth; height: parent.height - 2 * parent.verticalGap
            radius: 22; color: carPalette.card
            Text { anchors.centerIn: parent; width: parent.width - 40; wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter; color: carPalette.secondary; font.pixelSize: 26
                visible: !carController.dashboardMapApp
                text: qsTranslate("Sailplay", "Choose a map app in Sailplay") }
            MouseArea {
                anchors.fill: parent
                enabled: !!carController.dashboardMapApp
                onClicked: carController.dockClicked(carController.dashboardMapApp)
            }
        }
        Rectangle {
            id: musicCard
            x: carController.musicActive ? 16 : parent.mapWidth + 32
            y: carController.musicActive ? parent.verticalGap : weatherCard.y + weatherCard.height + parent.verticalGap
            width: carController.musicActive ? parent.width - 32 : parent.width - parent.mapWidth - 48
            height: parent.height - y - parent.verticalGap
            radius: 22; color: carPalette.card
            property var player: lockscreenMusic.mprisController
            property string artworkKey: player ? String(player.metaData.artUrl || player.metaData.url || "") : ""
            property url artwork: ""
            onArtworkKeyChanged: refreshArtwork()
            function refreshArtwork() {
                artwork = player ? carController.artworkSource(player.metaData.artUrl || "", player.metaData.url || "") : ""
            }
            Connections {
                target: carController
                onArtworkAvailable: if (key === musicCard.artworkKey) musicCard.artwork = localUrl
            }
            function openMusic() {
                carController.openMusic()
            }
            MouseArea { anchors.fill: parent; onClicked: musicCard.openMusic() }
            MusicPlayer {
                id: lockscreenMusic
                compact: !carController.musicActive
                width: parent.width - 64; x: 32
                y: Math.max(12, (musicCard.height - (compact ? 106 : 140) - height) / 2)
                albumArtSource: musicCard.artwork
                onClicked: musicCard.openMusic()
            }
            Item {
                id: musicProgress
                z: 2
                x: 32; width: parent.width - 64; height: carController.musicActive ? 112 : 90
                y: lockscreenMusic.y + lockscreenMusic.height + 4
                visible: lockscreenMusic.visible && !lockscreenMusic.idleCard
                property var player: lockscreenMusic.mprisController
                // Amber metadata duration is milliseconds; queried MPRIS Position is microseconds.
                property real durationSeconds: player ? Math.max(0, Number(player.metaData.duration || 0) / 1000) : 0
                property real positionSeconds: 0
                property string trackKey: player ? [player.currentService || "", String(player.metaData.trackId || ""),
                    player.metaData.url || "", player.metaData.title || ""].join("|") : ""
                onTrackKeyChanged: { positionSeconds = 0; refresh() }
                property var seekTrackId
                property string seekService
                function timeText(seconds) {
                    var n = Math.max(0, Math.floor(seconds))
                    var minutes = Math.floor(n / 60)
                    return minutes + ":" + (n % 60 < 10 ? "0" : "") + (n % 60)
                }
                function refresh() {
                    if (player && player.currentService)
                        carController.requestPlayerPosition(player.currentService, trackKey)
                    else positionSeconds = 0
                }
                function applyPosition(seconds) {
                    positionSeconds = Math.max(0, seconds)
                    if (!seekSlider.pressed)
                        seekSlider.value = Math.min(durationSeconds || positionSeconds, positionSeconds)
                }
                Timer {
                    interval: 1000; repeat: true; triggeredOnStart: true
                    running: musicProgress.visible && !!musicProgress.player
                    onTriggered: musicProgress.refresh()
                }
                Connections {
                    target: musicProgress.player
                    onPositionChanged: musicProgress.refresh()
                    onPlaybackStatusChanged: musicProgress.refresh()
                    onSeeked: musicProgress.refresh()
                }
                Connections {
                    target: carController
                    onPlayerPositionAvailable: {
                        if (musicProgress.player && service === musicProgress.player.currentService
                                && trackKey === musicProgress.trackKey)
                            musicProgress.applyPosition(seconds)
                    }
                }
                Silica.Slider {
                    id: seekSlider
                    Binding { target: seekSlider; property: "color"; when: carPalette.day; value: "transparent" }
                    Binding { target: seekSlider; property: "backgroundColor"; when: carPalette.day; value: "transparent" }
                    Binding { target: seekSlider; property: "highlightColor"; when: carPalette.day; value: "transparent" }
                    Binding { target: seekSlider; property: "backgroundGlowColor"; when: carPalette.day; value: "transparent" }
                    Item {
                        anchors.fill: parent; z: 3; visible: carPalette.day
                        opacity: seekSlider.enabled ? 1 : 0.5
                        Rectangle {
                            id: dayTrack
                            x: seekSlider.leftMargin; y: parent.height / 2 - 2
                            width: Math.max(0, parent.width - seekSlider.leftMargin - seekSlider.rightMargin)
                            height: 4; radius: 2; color: carPalette.disabled
                            property real progress: Math.max(0, Math.min(1, (seekSlider.value - seekSlider.minimumValue) / Math.max(1, seekSlider.maximumValue - seekSlider.minimumValue)))
                            Rectangle { width: parent.width * parent.progress; height: parent.height; radius: 2; color: carPalette.text }
                            Rectangle { x: parent.width * parent.progress - width / 2; y: (parent.height - height) / 2; width: 14; height: 14; radius: 7; color: carPalette.text }
                        }
                    }
                    width: parent.width; height: carController.musicActive ? 72 : 56
                    minimumValue: 0; maximumValue: Math.max(1, musicProgress.durationSeconds)
                    stepSize: 1
                    enabled: !!musicProgress.player && musicProgress.player.canSeek && musicProgress.durationSeconds > 0
                    onPressedChanged: {
                        if (!musicProgress.player) return
                        if (pressed) {
                            musicProgress.seekTrackId = musicProgress.player.metaData.trackId
                            musicProgress.seekService = musicProgress.player.currentService
                        } else if (enabled && musicProgress.seekService === musicProgress.player.currentService)
                            carController.seekPlayer(musicProgress.seekService, musicProgress.seekTrackId, value)
                    }
                }
                Text {
                    x: 8; y: carController.musicActive ? 76 : 58; color: carPalette.secondary; font.pixelSize: 24
                    text: musicProgress.timeText(seekSlider.pressed ? seekSlider.value : musicProgress.positionSeconds)
                }
                Text {
                    anchors.right: parent.right; anchors.rightMargin: 8
                    y: carController.musicActive ? 76 : 58; color: carPalette.secondary; font.pixelSize: 24
                    text: musicProgress.durationSeconds > 0 ? musicProgress.timeText(musicProgress.durationSeconds) : "--:--"
                }
            }
            Text {
                anchors.centerIn: parent; width: parent.width - 64; wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter; color: carPalette.secondary; font.pixelSize: 26
                visible: !lockscreenMusic.visible
                text: qsTranslate("Sailplay", "No music playing\nStart music on your phone")
            }
            Rectangle {
                anchors.bottom: parent.bottom; anchors.bottomMargin: 20
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width - 64; height: 56; radius: 16; color: carPalette.button
                visible: !lockscreenMusic.visible
                Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Open music app"); font.pixelSize: 24; color: carPalette.text }
                MouseArea { anchors.fill: parent; onClicked: carController.ensureMusicBackend() }
            }
        }
    }
    Row {
        visible: pages.visible; y: root.height - 45; x: dock.width + (pages.width - width) / 2; spacing: 16
        Repeater {
            model: root.pageCount
            Rectangle {
                width: 12; height: 12; radius: 6; color: index === pages.currentIndex ? carPalette.text : carPalette.inactiveDot
                MouseArea { anchors.fill: parent; anchors.margins: -12; onClicked: pages.goToPage(index) }
            }
        }
    }
    Rectangle {
        visible: root.notice !== ""
        x: dock.width + 180; y: root.height - 132
        width: root.width - x - 180; height: 66; radius: 16; color: carPalette.notice
        Text { anchors.centerIn: parent; text: root.notice; color: carPalette.text; font.pixelSize: 28 }
    }
    }
}
