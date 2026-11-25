import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    id: page
    allowedOrientations: Orientation.All

    function selectLocation(key) {
        if (carController.setDashboardWeather(key)) pageStack.pop()
        else notice.text = qsTranslate("Sailplay", "Could not save weather selection")
    }

    SilicaListView {
        anchors.fill: parent
        model: carController.weatherLocations
        header: Column {
            width: page.width
            PageHeader { title: qsTranslate("Sailplay", "Dashboard weather") }
            Label {
                x: Theme.horizontalPageMargin; width: parent.width - 2 * x
                wrapMode: Text.WordWrap; font.pixelSize: Theme.fontSizeSmall; color: Theme.secondaryColor
                text: qsTranslate("Sailplay", "Choose a saved Weather location. Add locations in the Weather app; Sailplay uses their cached conditions.")
            }
            ListItem {
                objectName: "dashboardWeatherOffOption"
                width: parent.width; contentHeight: Theme.itemSizeMedium
                onClicked: page.selectLocation("")
                Label {
                    x: Theme.horizontalPageMargin; width: parent.width - 2 * x
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTranslate("Sailplay", "Not set")
                    color: carController.dashboardWeatherLocation === "" ? Theme.highlightColor : Theme.primaryColor
                }
            }
            Label {
                id: notice
                x: Theme.horizontalPageMargin; width: parent.width - 2 * x
                wrapMode: Text.WordWrap; color: Theme.highlightColor
                text: carController.weatherLocations.length ? "" : qsTranslate("Sailplay", "No saved weather locations")
            }
        }
        delegate: ListItem {
            objectName: "dashboardWeatherOption_" + index
            width: page.width; contentHeight: Theme.itemSizeLarge
            onClicked: page.selectLocation(modelData.key)
            Column {
                x: Theme.horizontalPageMargin; width: parent.width - 2 * x
                anchors.verticalCenter: parent.verticalCenter
                Label {
                    width: parent.width; text: modelData.city
                    textFormat: Text.PlainText; truncationMode: TruncationMode.Fade
                    color: carController.dashboardWeatherLocation === modelData.key ? Theme.highlightColor : Theme.primaryColor
                }
                Label {
                    width: parent.width; text: modelData.country || ""
                    textFormat: Text.PlainText; font.pixelSize: Theme.fontSizeSmall; color: Theme.secondaryColor
                    truncationMode: TruncationMode.Fade
                }
            }
        }
        VerticalScrollDecorator {}
    }
}
