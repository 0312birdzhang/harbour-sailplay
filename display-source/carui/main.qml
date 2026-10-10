import QtQuick 2.0
import QtQuick.Window 2.0
import Sailfish.Silica 1.0 as Silica
import Sailfish.Media 1.0 as Media
Window {
    id: projectionWindow
    visible: true; width: Number(Qt.application.arguments[2] || 1920); height: Number(Qt.application.arguments[3] || 720); color: "#17203a"
    title: "Sailife UI" // Compositor fullscreen-shell identifier.
    Item {
    id: root
    width: 1920; height: projectionWindow.height / scale
    scale: projectionWindow.width / 1920
    transformOrigin: Item.TopLeft
    property string clockText: Qt.formatDateTime(new Date(), "hh:mm")
    property var status: carController.status
    property var apps: carController.tiles
    property int pageCount: Math.max(1, Math.ceil((apps.length + 1) / 8))
    property int battery: status.battery === undefined ? -1 : status.battery
    property int mobile: status.mobileStrength === undefined ? -1 : status.mobileStrength
    property string notice: ""
    Timer { id: noticeTimer; interval: 5000; onTriggered: root.notice = "" }
    Timer { interval: 15000; running: true; repeat: true; onTriggered: root.clockText = Qt.formatDateTime(new Date(), "hh:mm") }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: "#263657" }
            GradientStop { position: 0.55; color: "#17203a" }
            GradientStop { position: 1; color: "#382439" }
        }
    }
    Rectangle {
        id: dock
        width: 140; height: parent.height; color: "#dd090c14"
        Text { y: 25; anchors.horizontalCenter: parent.horizontalCenter; text: root.clockText; color: "white"; font.pixelSize: 37; font.bold: true }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter; y: 83; spacing: 7
            Row {
                visible: root.status.mobileSupported === true; spacing: 3; height: 24
                Repeater {
                    model: 4
                    Rectangle {
                        width: 7; height: 7 + index * 5; anchors.bottom: parent.bottom; radius: 1
                        color: root.mobile >= (index + 1) * 25 ? "white" : "#596071"
                    }
                }
            }
            Text { visible: root.status.mobileSupported === true; width: 33; text: root.mobile < 0 ? "—" : (root.status.mobileType || ""); color: "white"; font.pixelSize: 18; anchors.verticalCenter: parent.verticalCenter }
            Canvas {
                width: 32; height: 27
                property int strength: root.status.wifiConnected ? root.status.wifiStrength : -1
                onStrengthChanged: requestPaint()
                onPaint: {
                    var c = getContext("2d"); c.clearRect(0, 0, width, height); c.lineWidth = 3; c.lineCap = "round"
                    for (var i = 0; i < 3; i++) {
                        c.strokeStyle = strength >= (i * 33 + 1) ? "white" : "#596071"
                        c.beginPath(); c.arc(16, 25, 6 + i * 7, Math.PI * 1.24, Math.PI * 1.76); c.stroke()
                    }
                    c.fillStyle = strength >= 0 ? "white" : "#596071"; c.beginPath(); c.arc(16, 24, 2, 0, Math.PI * 2); c.fill()
                }
            }
        }
        Row {
            y: 127; anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
            Rectangle {
                width: 38; height: 20; radius: 4; color: "transparent"; border.width: 2; border.color: root.battery >= 0 ? "white" : "#596071"
                Rectangle { x: 4; y: 4; height: 12; width: Math.max(0, 30 * root.battery / 100); radius: 1; color: root.status.charging ? "#55dc83" : root.battery <= 20 ? "#ff675c" : "white" }
                Rectangle { x: 39; y: 6; width: 3; height: 8; radius: 1; color: "#aeb5c5" }
                Text { anchors.centerIn: parent; text: root.status.charging ? "ϟ" : ""; color: "#14251a"; font.pixelSize: 20 }
            }
            Text { text: root.battery < 0 ? "—" : root.battery + "%"; color: "white"; font.pixelSize: 18 }
        }
        Repeater {
            model: carController.dockApps.slice(0, 3)
            Rectangle {
                x: 25; y: 207 + index * 121; width: 90; height: 90; radius: 21; color: dockTouch.pressed ? "#526795" : "#263249"
                Image { anchors.centerIn: parent; width: 78; height: 78; fillMode: Image.PreserveAspectFit; source: modelData.icon ? "file://" + modelData.icon : ""; visible: source !== "" }
                Text { anchors.centerIn: parent; text: modelData.icon ? "" : modelData.name.charAt(0); color: "white"; font.pixelSize: 38 }
                MouseArea { id: dockTouch; anchors.fill: parent; onClicked: carController.dockClicked(modelData.appId) }
            }
        }
        Rectangle {
            x: 25; y: parent.height - 178; width: 90; height: 58; radius: 16
            color: carController.dashboardActive ? "#526795" : "#263249"
            Text { anchors.centerIn: parent; text: "◫"; color: "white"; font.pixelSize: 42 }
            MouseArea { anchors.fill: parent; onClicked: carController.openDashboard() }
        }
        Rectangle {
            x: 25; y: parent.height - 108; width: 90; height: 86; radius: 22; color: homeTouch.pressed ? "#526795" : "transparent"
            Grid { anchors.centerIn: parent; columns: 3; spacing: 5; Repeater { model: 9; Rectangle { width: 11; height: 11; radius: 3; color: "white" } } }
            MouseArea { id: homeTouch; anchors.fill: parent; onClicked: carController.homeClicked() }
        }
    }
    Silica.SlideshowView {
        id: pages
        visible: carController.currentApp === "" && !carController.dashboardActive
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
                x: 40; y: 22; columns: 4
                Repeater {
                    model: 8
                    Item {
                        property int appIndex: parent.parent.pageIndex * 8 + index - 1
                        property bool oem: appIndex === -1
                        property var entry: appIndex >= 0 && appIndex < root.apps.length ? root.apps[appIndex] : null
                        visible: oem || entry !== null
                        width: (pages.width - 80) / 4; height: (pages.height - 35) / 2
                        Rectangle {
                            y: 27; anchors.horizontalCenter: parent.horizontalCenter
                            width: 156; height: 156; radius: 34; color: oem ? "#718294" : "#324560"; opacity: appTouch.pressed ? 0.65 : 1
                            Image { anchors.fill: parent; anchors.margins: 8; fillMode: Image.PreserveAspectFit; source: entry && entry.icon ? "file://" + entry.icon : ""; visible: !oem && source !== "" }
                            Text { anchors.centerIn: parent; visible: !oem && entry && !entry.icon; text: entry ? entry.name.charAt(0) : ""; font.pixelSize: 76; color: "white" }
                            Canvas {
                                anchors.centerIn: parent; width: 112; height: 98; visible: oem
                                onPaint: {
                                    var c = getContext("2d"); c.lineWidth = 5; c.strokeStyle = "white"; c.lineJoin = "round"
                                    c.beginPath(); c.moveTo(15, 45); c.lineTo(29, 17); c.lineTo(83, 17); c.lineTo(97, 45); c.closePath(); c.stroke()
                                    c.strokeRect(12, 45, 88, 34); c.fillStyle = "white"
                                    c.fillRect(17, 55, 15, 6); c.fillRect(80, 55, 15, 6); c.fillRect(18, 80, 12, 12); c.fillRect(82, 80, 12, 12)
                                }
                            }
                        }
                        Text { y: 203; width: parent.width - 20; anchors.horizontalCenter: parent.horizontalCenter; text: oem ? "返回车机" : entry ? entry.name : ""; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; font.pixelSize: 31; color: "white" }
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
        visible: carController.dashboardActive
        x: dock.width; width: root.width - x; height: root.height
        property real mapWidth: (width - 48) * 0.65
        Text { x: 24; y: 14; text: "地图"; font.pixelSize: 30; color: "white" }
        Text { x: parent.mapWidth + 40; y: 14; text: "音乐"; font.pixelSize: 30; color: "white" }
        Rectangle {
            x: 16; y: 64; width: parent.mapWidth; height: parent.height - 80
            radius: 22; color: "#263249"
            property var player: lockscreenMusic.item ? lockscreenMusic.item.mprisController : null
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
            Text { anchors.centerIn: parent; width: parent.width - 40; wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter; color: "#aebcd4"; font.pixelSize: 26
                visible: !carController.dashboardMapApp
                text: "在 Sailplay App 中选择地图应用" }
            MouseArea {
                anchors.fill: parent
                enabled: !!carController.dashboardMapApp
                onClicked: carController.dockClicked(carController.dashboardMapApp)
            }
        }
        Rectangle {
            id: musicCard
            x: parent.mapWidth + 32; y: 64; width: parent.width - parent.mapWidth - 48; height: parent.height - 80
            radius: 22; color: "#263249"
            function openMusic() {
                if (carController.dashboardMusicApp)
                    carController.dockClicked(carController.dashboardMusicApp)
            }
            MouseArea { anchors.fill: parent; onClicked: musicCard.openMusic() }
            Media.MprisPlayerControls {
                id: lockscreenMusic
                onLoaded: {
                    // The system loader reparents its controls to this card.
                    item.width = Qt.binding(function() { return musicCard.width - 64 })
                    item.x = 32
                    item.y = Qt.binding(function() { return Math.max(24, (musicCard.height - 140 - item.height) / 2) })
                    item.clicked.connect(musicCard.openMusic)
                    item.albumArtSource = Qt.binding(function() { return musicCard.artwork })
                    musicCard.refreshArtwork()
                }
            }
            // Override the system title area's play/pause shortcut. Buttons
            // in the bottom row retain their original handlers.
            MouseArea {
                visible: !!lockscreenMusic.item
                z: 2
                x: 32; width: parent.width - 64
                y: lockscreenMusic.item ? lockscreenMusic.item.y : 0
                height: lockscreenMusic.item ? Math.max(0, lockscreenMusic.item.height - lockscreenMusic.item._squareSize) : 0
                onClicked: musicCard.openMusic()
            }
            Item {
                id: musicProgress
                z: 2
                x: 32; width: parent.width - 64; height: 112
                y: lockscreenMusic.item ? lockscreenMusic.item.y + lockscreenMusic.item.height + 16 : 0
                visible: !!lockscreenMusic.item
                property var player: lockscreenMusic.item ? lockscreenMusic.item.mprisController : null
                // Amber.Mpris exposes position in milliseconds, duration in seconds.
                property real durationSeconds: player ? Math.max(0, Number(player.metaData.duration || 0)) : 0
                property real positionSeconds: 0
                property var seekTrackId
                property string seekService
                function timeText(seconds) {
                    var n = Math.max(0, Math.floor(seconds))
                    var minutes = Math.floor(n / 60)
                    return minutes + ":" + (n % 60 < 10 ? "0" : "") + (n % 60)
                }
                function refresh() {
                    positionSeconds = player ? Math.max(0, Number(player.position) / 1000) : 0
                    if (!seekSlider.pressed)
                        seekSlider.value = Math.min(durationSeconds || positionSeconds, positionSeconds)
                }
                Timer {
                    interval: 1000; repeat: true; triggeredOnStart: true
                    running: musicProgress.visible && carController.dashboardActive && !!musicProgress.player
                    onTriggered: musicProgress.refresh()
                }
                Connections {
                    target: musicProgress.player
                    onPositionChanged: musicProgress.refresh()
                    onPlaybackStatusChanged: musicProgress.refresh()
                }
                Silica.Slider {
                    id: seekSlider
                    width: parent.width; height: 72
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
                    x: 8; y: 76; color: "#aebcd4"; font.pixelSize: 24
                    text: musicProgress.timeText(seekSlider.pressed ? seekSlider.value : musicProgress.positionSeconds)
                }
                Text {
                    anchors.right: parent.right; anchors.rightMargin: 8
                    y: 76; color: "#aebcd4"; font.pixelSize: 24
                    text: musicProgress.durationSeconds > 0 ? musicProgress.timeText(musicProgress.durationSeconds) : "--:--"
                }
            }
            Text {
                anchors.centerIn: parent; width: parent.width - 64; wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter; color: "#aebcd4"; font.pixelSize: 26
                visible: !lockscreenMusic.item
                text: carController.dashboardMusicApp ? "打开音乐应用开始播放" : "暂无音乐播放\n在 Sailplay App 中选择音乐应用"
            }
            Rectangle {
                anchors.bottom: parent.bottom; anchors.bottomMargin: 20
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width - 64; height: 56; radius: 16; color: "#354460"
                visible: !!carController.dashboardMusicApp && !lockscreenMusic.item
                Text { anchors.centerIn: parent; text: "打开音乐应用"; font.pixelSize: 24; color: "white" }
                MouseArea { anchors.fill: parent; onClicked: carController.dockClicked(carController.dashboardMusicApp) }
            }
        }
    }
    Row {
        visible: pages.visible; y: root.height - 45; x: dock.width + (pages.width - width) / 2; spacing: 16
        Repeater {
            model: root.pageCount
            Rectangle {
                width: 12; height: 12; radius: 6; color: index === pages.currentIndex ? "white" : "#788193"
                MouseArea { anchors.fill: parent; anchors.margins: -12; onClicked: pages.goToPage(index) }
            }
        }
    }
    Rectangle {
        visible: root.notice !== ""
        x: dock.width + 180; y: root.height - 132
        width: root.width - x - 180; height: 66; radius: 16; color: "#ed111a2c"
        Text { anchors.centerIn: parent; text: root.notice; color: "white"; font.pixelSize: 28 }
    }
    }
}
