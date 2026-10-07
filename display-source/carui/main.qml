import QtQuick 2.0
import QtQuick.Window 2.0
Window {
    id: root
    visible: true; width: 1920; height: 720; color: "#17203a"
    title: "Sailife UI" // Compositor fullscreen-shell identifier.
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
            x: 16; y: 83; spacing: 7
            Row {
                spacing: 3; height: 24
                Repeater {
                    model: 4
                    Rectangle {
                        width: 7; height: 7 + index * 5; anchors.bottom: parent.bottom; radius: 1
                        color: root.mobile >= (index + 1) * 25 ? "white" : "#596071"
                    }
                }
            }
            Text { width: 33; text: root.mobile < 0 ? "—" : (root.status.mobileType || ""); color: "white"; font.pixelSize: 18; anchors.verticalCenter: parent.verticalCenter }
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
            x: 25; y: parent.height - 108; width: 90; height: 86; radius: 22; color: homeTouch.pressed ? "#526795" : "transparent"
            Grid { anchors.centerIn: parent; columns: 3; spacing: 5; Repeater { model: 9; Rectangle { width: 11; height: 11; radius: 3; color: "white" } } }
            MouseArea { id: homeTouch; anchors.fill: parent; onClicked: carController.homeClicked() }
        }
    }
    ListView {
        id: pages
        visible: carController.currentApp === ""
        x: dock.width; width: root.width - x; height: root.height - 66
        orientation: ListView.Horizontal; snapMode: ListView.SnapOneItem
        boundsBehavior: Flickable.StopAtBounds; highlightRangeMode: ListView.StrictlyEnforceRange
        preferredHighlightBegin: 0; preferredHighlightEnd: 0; highlightMoveDuration: 230
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
    Row {
        visible: pages.visible; y: root.height - 45; x: dock.width + (pages.width - width) / 2; spacing: 16
        Repeater {
            model: root.pageCount
            Rectangle {
                width: 12; height: 12; radius: 6; color: index === pages.currentIndex ? "white" : "#788193"
                MouseArea { anchors.fill: parent; anchors.margins: -12; onClicked: pages.currentIndex = index }
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
