import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica
import Sailfish.Weather 1.0 as Weather

Rectangle {
    CarPalette { id: carPalette }
    id: card
    radius: 22; color: carPalette.card
    // Reuse the Events View weather cache; never require Internet on vehicle Wi-Fi.
    Weather.SavedWeathersModel {
        id: saved
        autoRefresh: true
        provider: Weather.WeatherProvider.currentProvider()
    }
    Weather.WeatherModel {
        weather: card.weather
        savedWeathers: saved
        active: card.visible && !!card.weather
    }
    property var weather: saved.currentWeather
    readonly property bool populated: !!weather && weather.populated
    Row {
        anchors.centerIn: parent; spacing: 22
        width: parent.width - 48
        Weather.WeatherImage {
            id: weatherIcon
            width: Math.min(132, card.height - 40); height: width
            anchors.verticalCenter: parent.verticalCenter
            weatherType: card.populated ? card.weather.weatherType : ""
            source: weatherType.length ? "image://theme/graphic-weather-" + weatherType + (carPalette.day ? "?" + carPalette.text : "") : ""
        }
        Column {
            width: parent.width - weatherIcon.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter; spacing: 8
            Text {
                width: parent.width; color: carPalette.text; font.pixelSize: 62
                font.family: Silica.Theme.fontFamilyHeading
                text: card.populated ? Weather.TemperatureConverter.format(card.weather.temperature) : "—°"
            }
            Text {
                width: parent.width; color: carPalette.text; font.pixelSize: 28
                elide: Text.ElideRight
                text: card.weather ? card.weather.city : qsTranslate("Sailplay", "Set a location in Weather")
            }
        }
    }
}
