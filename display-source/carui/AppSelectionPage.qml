import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    id: page
    allowedOrientations: Orientation.All
    property bool showAllApps: false
    property var appEntries: []
    property bool authorizing: false
    property string saveNotice: ""

    function refreshApps() {
        appEntries = carController.availableApps(showAllApps)
    }
    function toggle(appId) {
        saveNotice = carController.toggleApp(appId)
                ? qsTranslate("Sailplay", "Saved automatically")
                : qsTranslate("Sailplay", "Save failed")
    }
    onShowAllAppsChanged: refreshApps()
    onStatusChanged: {
        if (status === PageStatus.Active) {
            carController.reloadConfig()
            refreshApps()
        }
    }
    Connections {
        target: carController
        onRowsChanged: page.refreshApps()
        onCommunicationPermissionsFinished: {
            page.authorizing = false
            page.saveNotice = successful ? qsTranslate("Sailplay", "Phone and messages authorized")
                                         : qsTranslate("Sailplay", "Authorization cancelled or failed")
        }
    }

    SilicaListView {
        id: appList
        objectName: "appSelectionList"
        anchors.fill: parent
        model: page.appEntries
        PullDownMenu {
            MenuItem {
                objectName: "authorizeCommunicationMenuItem"
                text: qsTranslate("Sailplay", "Authorize phone and messages")
                enabled: !page.authorizing
                onClicked: {
                    page.authorizing = true
                    carController.authorizeCommunicationApps()
                }
            }
            MenuItem {
                objectName: "showAllAppsMenuItem"
                text: page.showAllApps ? qsTranslate("Sailplay", "Show SDK apps")
                                       : qsTranslate("Sailplay", "Show all apps")
                onClicked: page.showAllApps = !page.showAllApps
            }
        }
        header: Column {
            width: page.width
            PageHeader { title: qsTranslate("Sailplay", "Car display apps") }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * Theme.horizontalPageMargin
                wrapMode: Text.WordWrap
                color: Theme.secondaryColor
                font.pixelSize: Theme.fontSizeSmall
                text: qsTranslate("Sailplay", "Select the SDK apps to show on the car display. Changes are saved and applied immediately.")
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * Theme.horizontalPageMargin
                wrapMode: Text.WordWrap
                color: Theme.highlightColor
                text: page.saveNotice
            }
            Item { width: 1; height: Theme.paddingMedium }
        }
        delegate: ListItem {
            width: page.width
            contentHeight: modelData.sdkIntegrated ? Theme.itemSizeSmall : Theme.itemSizeMedium
            enabled: modelData.sdkIntegrated
            onClicked: page.toggle(modelData.id)
            Image {
                id: appIcon
                x: Theme.horizontalPageMargin
                anchors.verticalCenter: parent.verticalCenter
                width: Theme.iconSizeMedium
                height: width
                fillMode: Image.PreserveAspectFit
                source: modelData.icon !== "" ? "file://" + modelData.icon : ""
            }
            Column {
                anchors.left: appIcon.right
                anchors.leftMargin: Theme.paddingLarge
                anchors.right: appSwitch.left
                anchors.rightMargin: Theme.paddingMedium
                anchors.verticalCenter: parent.verticalCenter
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    text: modelData.name
                    color: modelData.sdkIntegrated ? Theme.primaryColor : Theme.secondaryColor
                }
                Label {
                    width: parent.width
                    visible: !modelData.sdkIntegrated
                    truncationMode: TruncationMode.Fade
                    font.pixelSize: Theme.fontSizeExtraSmall
                    color: Theme.secondaryColor
                    text: qsTranslate("Sailplay", "Sailplay SDK integration required")
                }
            }
            Switch {
                id: appSwitch
                anchors.right: parent.right
                anchors.rightMargin: Theme.horizontalPageMargin
                anchors.verticalCenter: parent.verticalCenter
                automaticCheck: false
                visible: modelData.sdkIntegrated
                checked: carController.selectedApps.indexOf(modelData.id) >= 0
                onClicked: page.toggle(modelData.id)
            }
        }
        ViewPlaceholder {
            enabled: appList.count === 0
            text: qsTranslate("Sailplay", "No SDK apps installed")
        }
        VerticalScrollDecorator { }
    }
}
