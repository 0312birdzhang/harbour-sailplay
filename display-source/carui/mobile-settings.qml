import QtQuick 2.0
import Sailfish.Silica 1.0

ApplicationWindow {
    id: app
    readonly property bool useChinese: Qt.locale().name.indexOf("zh") === 0
    function textFor(english, chinese) { return useChinese ? chinese : english }
    function dashboardIndex(id) {
        var apps = carController.availableApps()
        for (var i = 0; i < apps.length; ++i) if (apps[i].id === id) return i + 1
        return 0
    }
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
                    SectionHeader { text: app.textFor("Dashboard", "仪表盘") }
                    ComboBox {
                        label: app.textFor("Map app", "地图应用")
                        currentIndex: app.dashboardIndex(carController.dashboardMapApp)
                        menu: ContextMenu {
                            MenuItem { text: app.textFor("Not selected", "未选择"); onClicked: carController.setDashboardApp("map", "") }
                            Repeater {
                                model: carController.availableApps()
                                delegate: MenuItem { text: modelData.name; onClicked: carController.setDashboardApp("map", modelData.id) }
                            }
                        }
                    }
                    ComboBox {
                        label: app.textFor("Music app", "音乐应用")
                        currentIndex: app.dashboardIndex(carController.dashboardMusicApp)
                        menu: ContextMenu {
                            MenuItem { text: app.textFor("Not selected", "未选择"); onClicked: carController.setDashboardApp("music", "") }
                            Repeater {
                                model: carController.availableApps()
                                delegate: MenuItem { text: modelData.name; onClicked: carController.setDashboardApp("music", modelData.id) }
                            }
                        }
                    }
                    Label {
                        x: Theme.horizontalPageMargin; width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap; font.pixelSize: Theme.fontSizeSmall; color: Theme.secondaryColor
                        text: app.textFor("The split panel shows the map and Sailfish lock-screen music controls for the current player. The music app is its launch shortcut.", "分屏左侧显示地图，右侧显示当前播放器的 Sailfish 锁屏音乐控件。音乐应用作为启动入口。")
                    }
                    SectionHeader { text: app.textFor("Car display home apps", "车机主页应用") }
                    ComboBox {
                        label: app.textFor("Resolution", "分辨率")
                        visible: carController.projectionResolutions.length > 0
                        currentIndex: carController.resolutionIndex
                        menu: ContextMenu {
                            MenuItem { text: carController.projectionResolutions[0] || ""; onClicked: carController.setProjectionSettings(0, carController.projectionFps) }
                            MenuItem { text: carController.projectionResolutions[1] || ""; onClicked: carController.setProjectionSettings(1, carController.projectionFps) }
                            MenuItem { text: carController.projectionResolutions[2] || ""; onClicked: carController.setProjectionSettings(2, carController.projectionFps) }
                        }
                    }
                    ComboBox {
                        label: app.textFor("Frame rate", "帧率")
                        currentIndex: carController.projectionFps === 60 ? 1 : 0
                        menu: ContextMenu {
                            MenuItem { text: Math.min(30, carController.maximumFps) + " fps"; onClicked: carController.setProjectionSettings(carController.resolutionIndex, 30) }
                            MenuItem { text: "60 fps"; visible: carController.maximumFps >= 60; onClicked: carController.setProjectionSettings(carController.resolutionIndex, 60) }
                        }
                    }
                    Label {
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * Theme.horizontalPageMargin
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.secondaryColor
                        text: carController.projectionResolutions.length > 0
                              ? app.textFor("Car display: ", "车机屏幕：") + carController.projectionResolutions[0]
                                + app.textFor("; maximum ", "；最高 ") + carController.maximumFps + " fps. "
                                + app.textFor("Lower resolutions reduce encoding load. Reconnect to apply.", "较低分辨率可降低编码负载，重新连接后生效。")
                              : app.textFor("Connect once to read the car display resolution and frame-rate limit.", "连接车机后读取屏幕分辨率和帧率上限。")
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
