import QtQuick 2.0

Rectangle {
    id: card
    property var provider
    property var palette
    property bool compact: false
    property var guidance: provider ? provider.guidance : ({})
    property bool navigating: guidance.state === "active"
    signal activated()
    radius: 22
    color: palette.card
    clip: true

    function distance(meters) {
        return meters >= 1000 ? (meters / 1000).toFixed(1) + " km" : Math.round(meters) + " m"
    }
    function symbol(maneuver) {
        var symbols = {
            "continue": "↑", "slight-left": "↖", "slight-right": "↗",
            "turn-left": "←", "turn-right": "→", "sharp-left": "↙", "sharp-right": "↘",
            "exit-left": "↙", "exit-right": "↘", "uturn": "↶",
            "roundabout-enter": "⟳", "roundabout-exit": "⟳", "roundabout-continue": "⟳", "arrive": "⚑"
        }
        var result = symbols[maneuver] || ""
        if (maneuver === "uturn" && guidance.drivingSide === "left") result = "↷"
        if (maneuver.indexOf("roundabout-") === 0 && guidance.drivingSide === "left") result = "⟲"
        if (maneuver === "roundabout-exit" && guidance.exitNumber > 0) result += " " + guidance.exitNumber
        return result
    }
    function statusText() {
        if (provider && provider.error) return provider.error
        if (!provider || !provider.ready) return qsTranslate("Sailplay", "Connecting navigation")
        var states = {
            "idle": qsTranslate("Sailplay", "Ready for navigation"),
            "unavailable": qsTranslate("Sailplay", "Navigation unavailable"),
            "stopped": qsTranslate("Sailplay", "Navigation stopped"),
            "arrived": qsTranslate("Sailplay", "You have arrived")
        }
        return states[guidance.state] || ""
    }

    Column {
        width: Math.max(0, card.width - 48)
        anchors.centerIn: parent
        spacing: compact ? 12 : 20
        Text {
            width: parent.width
            text: provider ? provider.name : ""
            color: palette.secondary
            font.pixelSize: compact ? 24 : 30
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            visible: navigating
            text: card.symbol(guidance.maneuver || "unknown")
            color: palette.text
            font.pixelSize: compact ? 78 : 108
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            visible: navigating
            text: card.distance(guidance.nextDistanceMeters || 0)
            color: palette.text
            font.pixelSize: compact ? 34 : 44
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            width: parent.width
            text: navigating ? guidance.nextRoad : card.statusText()
            color: palette.text
            font.pixelSize: compact ? 26 : 34
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            maximumLineCount: compact ? 2 : 3
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            visible: navigating
            text: qsTranslate("Sailplay", "%1 min").arg(Math.ceil((guidance.remainingSeconds || 0) / 60))
                  + " · " + card.distance(guidance.remainingDistanceMeters || 0)
            color: palette.secondary
            font.pixelSize: compact ? 24 : 28
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
        Rectangle {
            visible: !compact && navigating
            width: Math.min(parent.width, 340)
            height: 66
            anchors.horizontalCenter: parent.horizontalCenter
            radius: 16
            color: palette.dock
            Text {
                anchors.centerIn: parent
                text: qsTranslate("Sailplay", "Stop navigation")
                color: palette.text
                font.pixelSize: 28
            }
            MouseArea { anchors.fill: parent; onClicked: provider.stopNavigation() }
        }
    }
    MouseArea {
        anchors.fill: parent
        enabled: compact
        onClicked: card.activated()
    }
}
