import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica
import Sailfish.Weather 1.0 as Weather

Rectangle {
    CarPalette { id: carPalette }
    id: card
    // DashboardInfoCard, which hosts this card, already draws the surface.
    radius: 22; color: "transparent"
    property var weather: carController.dashboardWeather
    readonly property bool configured: !!weather && !!weather.city
    readonly property bool populated: configured && weather.populated === true
    Row {
        anchors.centerIn: parent; spacing: 22
        width: parent.width - 48
        visible: card.configured
        Weather.WeatherImage {
            id: weatherIcon
            width: Math.max(0, Math.min(132, card.height - 40, (card.width - 70) * 0.34)); height: width
            anchors.verticalCenter: parent.verticalCenter
            weatherType: card.populated ? card.weather.weatherType : ""
            source: weatherType.length ? "image://theme/graphic-weather-" + weatherType + (carPalette.day ? "?" + carPalette.text : "") : ""
        }
        Column {
            width: parent.width - weatherIcon.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter; spacing: 8
            Text {
                objectName: "dashboardWeatherTemperature"
                width: parent.width; color: carPalette.text; font.pixelSize: Math.min(62, card.height * 0.32, (card.width - 70) * 0.32)
                font.family: Silica.Theme.fontFamilyHeading
                text: card.populated ? Weather.TemperatureConverter.format(card.weather.temperature) : "—°"
            }
            Text {
                objectName: "dashboardWeatherCity"
                width: parent.width; color: carPalette.text; font.pixelSize: 28
                elide: Text.ElideRight
                text: card.weather.city || ""
                textFormat: Text.PlainText
            }
        }
    }
    Text {
        objectName: "dashboardWeatherPlaceholder"
        anchors.centerIn: parent; width: parent.width - 48
        visible: !card.configured
        text: carController.dashboardWeatherLocation ? qsTranslate("Sailplay", "Weather location unavailable")
                                                    : qsTranslate("Sailplay", "Set dashboard weather in Sailplay")
        color: carPalette.secondary; font.pixelSize: 24
        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
    }
}
