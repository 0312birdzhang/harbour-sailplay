import QtQuick 2.0
import Sailfish.Silica 1.0

ApplicationWindow {
    id: app
    function dashboardIndex(id) {
        var apps = carController.availableApps()
        for (var i = 0; i < apps.length; ++i) if (apps[i].id === id) return i + 1
        return 0
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
            function toggle(appId) {
                if (!carController.toggleApp(appId))
                    saveNotice.text = qsTranslate("Sailplay", "Save failed")
                else
                    saveNotice.text = qsTranslate("Sailplay", "Saved automatically")
            }

            SilicaFlickable {
                anchors.fill: parent
                contentHeight: content.height
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
                    SectionHeader { text: qsTranslate("Sailplay", "Dashboard") }
                    ComboBox {
                        label: qsTranslate("Sailplay", "Map app")
                        currentIndex: app.dashboardIndex(carController.dashboardMapApp)
                        menu: ContextMenu {
                            MenuItem { text: qsTranslate("Sailplay", "Not selected"); onClicked: carController.setDashboardApp("map", "") }
                            Repeater {
                                model: carController.availableApps()
                                delegate: MenuItem { text: modelData.name; onClicked: carController.setDashboardApp("map", modelData.id) }
                            }
                        }
                    }
                    Label {
                        x: Theme.horizontalPageMargin; width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap; font.pixelSize: Theme.fontSizeSmall; color: Theme.secondaryColor
                        text: qsTranslate("Sailplay", "The music app stays on the phone; both screens control the same playback.")
                    }
                    SectionHeader { text: qsTranslate("Sailplay", "Car display home apps") }
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
                    Label {
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap
                        color: Theme.secondaryColor
                        font.pixelSize: Theme.fontSizeSmall
                        text: qsTranslate("Sailplay", "Select the apps to show on the car display home screen. Changes are saved and applied immediately.")
                    }
                    Repeater {
                        model: carController.availableApps()
                        delegate: ListItem {
                            width: page.width
                            contentHeight: Theme.itemSizeSmall
                            onClicked: page.toggle(modelData.id)
                            Image {
                                id: appIcon
                                x: Theme.horizontalPageMargin
                                anchors.verticalCenter: parent.verticalCenter
                                width: Theme.iconSizeMedium
                                height: width
                                fillMode: Image.PreserveAspectFit
                                source: modelData.icon !== ""
                                      ? "file://" + modelData.icon : ""
                            }
                            Label {
                                anchors.left: appIcon.right
                                anchors.leftMargin: Theme.paddingLarge
                                anchors.right: appSwitch.left
                                anchors.rightMargin: Theme.paddingMedium
                                anchors.verticalCenter: parent.verticalCenter
                                truncationMode: TruncationMode.Fade
                                text: modelData.name
                            }
                            Switch {
                                id: appSwitch
                                anchors.right: parent.right
                                anchors.rightMargin: Theme.horizontalPageMargin
                                anchors.verticalCenter: parent.verticalCenter
                                automaticCheck: false
                                checked: carController.selectedApps.indexOf(
                                             modelData.id) >= 0
                                onClicked: page.toggle(modelData.id)
                            }
                        }
                    }
                    Item { width: 1; height: Theme.paddingLarge }
                }
                VerticalScrollDecorator { }
            }
        }
    }
}
