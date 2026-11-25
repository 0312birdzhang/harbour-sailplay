import QtQuick 2.0
import "NavigationGuidance.js" as Guidance

Rectangle {
    id: card
    property var provider
    property var palette
    readonly property var guidance: provider ? provider.guidance : ({})
    readonly property bool navigating: !!provider && provider.ready && guidance.state === "active"
    radius: 22; color: palette.card
    clip: true

    WeatherCard {
        anchors.fill: parent
        visible: !card.navigating
    }
    Item {
        id: summary
        objectName: "dashboardNavigationSummary"
        visible: card.navigating
        readonly property real uiScale: Math.max(0.1, Math.min(card.width / 420, card.height / 170))
        width: card.width / uiScale; height: card.height / uiScale
        scale: uiScale; transformOrigin: Item.TopLeft
        Row {
            anchors.centerIn: parent
            width: parent.width - 32; spacing: 16
            Text {
                objectName: "dashboardManeuver"
                width: 100; height: 100
                anchors.verticalCenter: parent.verticalCenter
                text: Guidance.symbol(card.guidance.maneuver || "unknown", card.guidance.drivingSide, card.guidance.exitNumber)
                color: card.palette.text; font.pixelSize: 76
                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            }
            Column {
                width: parent.width - 116; spacing: 8
                Text {
                    objectName: "dashboardNextDistance"
                    width: parent.width; text: Guidance.distance(card.guidance.nextDistanceMeters || 0)
                    color: card.palette.text; font.pixelSize: 36; font.bold: true
                }
                Text {
                    objectName: "dashboardNextRoad"
                    width: parent.width; text: card.guidance.nextRoad || card.guidance.currentRoad || ""
                    textFormat: Text.PlainText; color: card.palette.text; font.pixelSize: 26; elide: Text.ElideRight
                }
                Text {
                    objectName: "dashboardRemainingRoute"
                    width: parent.width
                    text: qsTranslate("Sailplay", "%1 min").arg(Math.ceil((card.guidance.remainingSeconds || 0) / 60))
                          + " · " + Guidance.distance(card.guidance.remainingDistanceMeters || 0)
                    color: card.palette.secondary; font.pixelSize: 22; elide: Text.ElideRight
                }
            }
        }
    }
}
