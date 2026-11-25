import QtQuick 2.0
import "NavigationGuidance.js" as Guidance

Rectangle {
    id: card
    property var provider
    property var palette
    readonly property var guidance: provider ? provider.guidance : ({})
    readonly property bool navigating: !!provider && provider.navigating
    readonly property bool guidanceAvailable: navigating && provider.ready && guidance.state === "active"
    readonly property var lastGuidance: provider && provider.lastGuidance ? provider.lastGuidance : ({})
    readonly property bool showGuidance: guidanceAvailable || (navigating && !!lastGuidance && lastGuidance.state === "active")
    readonly property var displayGuidance: guidanceAvailable ? guidance : (showGuidance ? lastGuidance : ({}))
    readonly property var lastRoute: provider ? provider.lastRouteOverview : ({})
    radius: 22; color: palette.surface
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
        Column {
            anchors.centerIn: parent
            width: parent.width - 32
            spacing: 6
            visible: !card.showGuidance
            Text {
                objectName: "dashboardNavigationStatus"
                width: parent.width
                text: card.provider && card.provider.ready ? qsTranslate("Sailplay", "Waiting for navigation updates")
                                                           : qsTranslate("Sailplay", "Connecting navigation")
                color: card.palette.secondary; font.pixelSize: 25
                horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: card.lastRoute.destination || ""
                visible: !!text
                textFormat: Text.PlainText; color: card.palette.text; font.pixelSize: 32
                horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
            }
            Text {
                objectName: "dashboardLastRoute"
                width: parent.width
                visible: card.lastRoute.remainingDistanceMeters > 0 || card.lastRoute.remainingSeconds > 0
                text: visible ? qsTranslate("Sailplay", "Last update: %1 min · %2")
                    .arg(Math.ceil((card.lastRoute.remainingSeconds || 0) / 60))
                    .arg(Guidance.distance(card.lastRoute.remainingDistanceMeters || 0)) : ""
                color: card.palette.secondary; font.pixelSize: 24
                horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
            }
        }
        Row {
            visible: card.showGuidance
            anchors.centerIn: parent
            width: parent.width - 32; spacing: 16
            Text {
                objectName: "dashboardManeuver"
                width: 100; height: 100
                anchors.verticalCenter: parent.verticalCenter
                text: Guidance.symbol(card.displayGuidance.maneuver || "unknown", card.displayGuidance.drivingSide, card.displayGuidance.exitNumber)
                color: card.palette.text; font.pixelSize: 76
                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            }
            Column {
                width: parent.width - 116; spacing: 8
                Text {
                    objectName: "dashboardNextDistance"
                    width: parent.width; text: Guidance.distance(card.displayGuidance.nextDistanceMeters || 0)
                    color: card.palette.text; font.pixelSize: 36; font.bold: true
                }
                Text {
                    objectName: "dashboardNextRoad"
                    width: parent.width; text: card.displayGuidance.nextRoad || card.displayGuidance.currentRoad || ""
                    textFormat: Text.PlainText; color: card.palette.text; font.pixelSize: 26; elide: Text.ElideRight
                }
                Text {
                    objectName: "dashboardRemainingRoute"
                    width: parent.width
                    text: qsTranslate("Sailplay", "%1 min").arg(Math.ceil((card.displayGuidance.remainingSeconds || 0) / 60))
                          + " · " + Guidance.distance(card.displayGuidance.remainingDistanceMeters || 0)
                    color: card.palette.secondary; font.pixelSize: 22; elide: Text.ElideRight
                }
            }
        }
    }
}
