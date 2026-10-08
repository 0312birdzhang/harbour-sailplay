import QtQuick 2.0
import Sailfish.Silica 1.0

ApplicationWindow {
    id: app
    readonly property bool useChinese: Qt.locale().name.indexOf("zh") === 0
    function textFor(english, chinese) { return useChinese ? chinese : english }
    function serviceStateText(state) {
        var labels = { active: textFor("Running", "运行中"),
                       inactive: textFor("Stopped", "已停止"),
                       activating: textFor("Starting", "正在启动"),
                       deactivating: textFor("Stopping", "正在停止"),
                       failed: textFor("Failed", "启动失败"),
                       unknown: textFor("Unavailable", "无法读取") }
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
                    text: app.textFor("Car display apps", "车机应用管理")
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
                    saveNotice.text = app.textFor("Save failed", "保存失败")
                else
                    saveNotice.text = app.textFor("Saved automatically", "已自动保存")
            }

            SilicaFlickable {
                anchors.fill: parent
                contentHeight: content.height
                Column {
                    id: content
                    width: page.width
                    PageHeader { title: "Sailplay" }
                    SectionHeader { text: app.textFor("Projection service", "投屏服务") }
                    TextSwitch {
                        text: app.textFor("Enable Sailplay", "开启 Sailplay")
                        description: app.textFor("Service status: ", "服务状态：") + app.serviceStateText(carController.serviceState)
                        automaticCheck: false
                        checked: carController.serviceRunning
                        enabled: !carController.serviceBusy
                        onClicked: carController.setServiceRunning(!checked)
                    }
                    Button {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: carController.serviceBusy ? app.textFor("Processing…", "正在处理…")
                              : app.textFor("Connect / reconnect to car", "连接车机／重新连接")
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
                    SectionHeader { text: app.textFor("Car display home apps", "车机主页应用") }
                    ComboBox {
                        label: app.textFor("Resolution", "分辨率")
                        currentIndex: carController.resolutionIndex
                        menu: ContextMenu {
                            MenuItem { text: "1920 × 720"; onClicked: carController.setProjectionSettings(0, carController.projectionFps) }
                            MenuItem { text: "1600 × 600"; onClicked: carController.setProjectionSettings(1, carController.projectionFps) }
                            MenuItem { text: "1280 × 480"; onClicked: carController.setProjectionSettings(2, carController.projectionFps) }
                        }
                    }
                    ComboBox {
                        label: app.textFor("Frame rate", "帧率")
                        currentIndex: carController.projectionFps === 60 ? 1 : 0
                        menu: ContextMenu {
                            MenuItem { text: "30 fps"; onClicked: carController.setProjectionSettings(carController.resolutionIndex, 30) }
                            MenuItem { text: "60 fps"; onClicked: carController.setProjectionSettings(carController.resolutionIndex, 60) }
                        }
                    }
                    Label {
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.secondaryColor
                        text: app.textFor("Saved automatically. Tap Connect / reconnect to car to apply. Compatibility and performance depend on the car and device.", "自动保存，点击“连接车机／重新连接”后生效。实际效果取决于车机兼容性和设备性能。")
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
                        text: app.textFor("Select the apps to show on the car display home screen. Changes are saved and applied immediately.", "直接勾选需要显示在车机主页的应用，修改会立即保存并自动更新。")
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
