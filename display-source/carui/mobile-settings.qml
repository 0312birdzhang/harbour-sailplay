import QtQuick 2.0
import Sailfish.Silica 1.0

ApplicationWindow {
    id: app
    function chooseThemeTime(daytime, notice) {
        var parts = (daytime ? carController.dayStart : carController.nightStart).split(":")
        var dialog = pageStack.push("Sailfish.Silica.TimePickerDialog", {hour: Number(parts[0]), minute: Number(parts[1])})
        dialog.accepted.connect(function() {
            var time = (dialog.hour < 10 ? "0" : "") + dialog.hour + ":" + (dialog.minute < 10 ? "0" : "") + dialog.minute
            if (!carController.setThemeTime(daytime, time))
                notice.text = qsTranslate("Sailplay", "Choose different day and night times")
        })
    }
    function serviceStateText(state) {
        var labels = { active: qsTranslate("Sailplay", "Running"),
                       inactive: qsTranslate("Sailplay", "Stopped"),
                       activating: qsTranslate("Sailplay", "Starting"),
                       deactivating: qsTranslate("Sailplay", "Stopping"),
                       failed: qsTranslate("Sailplay", "Failed"),
                       unknown: qsTranslate("Sailplay", "Unavailable") }
        return labels[state] || state
    }
    allowedOrientations: Orientation.All
    cover: Component {
        CoverBackground {
            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 2 * Theme.paddingLarge
                spacing: Theme.paddingMedium
                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(parent.width, parent.height) * 0.62
                    height: width
                    fillMode: Image.PreserveAspectFit
                    source: "file:///opt/sailplay/carui/harbour-sailplay.png"
                }
                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTranslate("Sailplay", "Car display apps")
                    color: Theme.highlightColor
                    font.pixelSize: Theme.fontSizeSmall
                }
            }

        }
    }
    initialPage: Component {
        Page {
            id: page
            allowedOrientations: Orientation.All

            SilicaFlickable {
                anchors.fill: parent
                contentHeight: content.height
                PullDownMenu {
                    MenuItem {
                        objectName: "aboutMenuItem"
                        text: qsTranslate("Sailplay", "About")
                        onClicked: pageStack.push(Qt.resolvedUrl("AboutPage.qml"))
                    }
                }
                Column {
                    id: content
                    width: page.width
                    PageHeader { title: "Sailplay" }
                    SectionHeader { text: qsTranslate("Sailplay", "Projection service") }
                    TextSwitch {
                        text: qsTranslate("Sailplay", "Enable Sailplay")
                        description: qsTranslate("Sailplay", "Service status: %1").arg(app.serviceStateText(carController.serviceState))
                        automaticCheck: false
                        checked: carController.serviceRunning
                        enabled: !carController.serviceBusy
                        onClicked: carController.setServiceRunning(!checked)
                    }
                    ComboBox {
                        label: qsTranslate("Sailplay", "Projection protocol")
                        currentIndex: carController.projectionProtocolIndex
                        enabled: !carController.serviceBusy
                        menu: ContextMenu {
                            MenuItem { text: qsTranslate("Sailplay", "Automatic"); onClicked: carController.setProjectionProtocol(0) }
                            MenuItem { text: "CarPlay"; onClicked: carController.setProjectionProtocol(1) }
                            MenuItem { text: "Android Auto"; onClicked: carController.setProjectionProtocol(2) }
                        }
                    }
                    Label {
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.secondaryColor
                        text: qsTranslate("Sailplay", "Automatic prefers CarPlay when a car offers both protocols. Reconnect after changing the protocol.")
                    }
                    Label {
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap
                        color: Theme.highlightColor
                        text: {
                            var states = { connecting: qsTranslate("Sailplay", "Connecting"),
                                           projecting: qsTranslate("Sailplay", "Projecting"),
                                           restoring: qsTranslate("Sailplay", "Restoring Wi-Fi"),
                                           idle: qsTranslate("Sailplay", "Waiting for car") }
                            var state = states[carController.projectionConnectionState] || carController.projectionConnectionState
                            return carController.activeProjectionProtocol ? carController.activeProjectionProtocol + " — " + state
                                                                          : qsTranslate("Sailplay", "Waiting for car")
                        }
                    }
                    Button {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: carController.serviceBusy ? qsTranslate("Sailplay", "Processing…")
                              : qsTranslate("Sailplay", "Connect / reconnect to car")
                        enabled: !carController.serviceBusy
                        onClicked: carController.connectCar()
                    }
                    Label {
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * Theme.horizontalPageMargin
                        visible: text.length > 0
                        wrapMode: Text.WordWrap
                        color: Theme.highlightColor
                        text: carController.serviceError
                    }
                    SectionHeader { text: qsTranslate("Sailplay", "Car display theme") }
                    TextSwitch {
                        text: qsTranslate("Sailplay", "Follow phone ambience")
                        description: qsTranslate("Sailplay", "Uses the light or dark car theme of the current ambience, so projected apps stay readable. Turn off to switch by time of day.")
                        checked: carController.followAmbience
                        automaticCheck: false
                        onClicked: carController.setFollowAmbience(!checked)
                    }
                    ValueButton {
                        label: qsTranslate("Sailplay", "Day theme starts")
                        visible: !carController.followAmbience
                        value: carController.dayStart
                        onClicked: app.chooseThemeTime(true, saveNotice)
                    }
                    ValueButton {
                        label: qsTranslate("Sailplay", "Night theme starts")
                        visible: !carController.followAmbience
                        value: carController.nightStart
                        onClicked: app.chooseThemeTime(false, saveNotice)
                    }
                    Label {
                        x: Theme.horizontalPageMargin; width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap; font.pixelSize: Theme.fontSizeSmall; color: Theme.secondaryColor
                        text: qsTranslate("Sailplay", "Switches automatically using phone local time. Changes apply immediately to the car display.")
                        visible: !carController.followAmbience
                    }
                    SectionHeader { text: qsTranslate("Sailplay", "Dashboard") }
                    Label {
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.secondaryColor
                        text: qsTranslate("Sailplay", "SDK maps are detected automatically. The last map used on the car display opens next time.")
                    }
                    Label {
                        x: Theme.horizontalPageMargin; width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap; font.pixelSize: Theme.fontSizeSmall; color: Theme.secondaryColor
                        text: qsTranslate("Sailplay", "The music app stays on the phone; both screens control the same playback.")
                    }
                    SectionHeader { text: qsTranslate("Sailplay", "Car display home apps") }
                    ValueButton {
                        objectName: "appSelectionButton"
                        label: qsTranslate("Sailplay", "Manage displayed apps")
                        value: carController.selectedApps.length.toString()
                        onClicked: pageStack.push(Qt.resolvedUrl("AppSelectionPage.qml"))
                    }
                    SectionHeader { text: qsTranslate("Sailplay", "Car display") }
                    ComboBox {
                        label: qsTranslate("Sailplay", "Resolution")
                        visible: carController.projectionResolutions.length > 0
                        currentIndex: carController.resolutionIndex
                        menu: ContextMenu {
                            MenuItem { text: carController.projectionResolutions[0] || ""; onClicked: carController.setProjectionSettings(0, carController.projectionFps) }
                            MenuItem { text: carController.projectionResolutions[1] || ""; onClicked: carController.setProjectionSettings(1, carController.projectionFps) }
                            MenuItem { text: carController.projectionResolutions[2] || ""; onClicked: carController.setProjectionSettings(2, carController.projectionFps) }
                        }
                    }
                    ComboBox {
                        label: qsTranslate("Sailplay", "Frame rate")
                        currentIndex: carController.projectionFps === 60 ? 1 : 0
                        menu: ContextMenu {
                            MenuItem { text: qsTranslate("Sailplay", "%1 fps").arg(Math.min(30, carController.maximumFps)); onClicked: carController.setProjectionSettings(carController.resolutionIndex, 30) }
                            MenuItem { text: qsTranslate("Sailplay", "%1 fps").arg(60); visible: carController.maximumFps >= 60; onClicked: carController.setProjectionSettings(carController.resolutionIndex, 60) }
                        }
                    }
                    Label {
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.secondaryColor
                        text: carController.projectionResolutions.length > 0
                              ? qsTranslate("Sailplay", "Car display: %1; maximum %2 fps. Lower resolutions reduce encoding load. Reconnect to apply.")
                                .arg(carController.projectionResolutions[0]).arg(carController.maximumFps)
                              : qsTranslate("Sailplay", "Connect once to read the car display resolution and frame-rate limit.")
                    }
                    Label {
                        id: saveNotice
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * Theme.horizontalPageMargin
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.highlightColor
                    }
                    Item { width: 1; height: Theme.paddingLarge }
                }
                VerticalScrollDecorator { }
            }
        }
    }
}
