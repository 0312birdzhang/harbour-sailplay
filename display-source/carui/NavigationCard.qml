import QtQuick 2.0
import Sailplay 1.0

Rectangle {
    id: card
    property var provider
    property var palette
    property bool compact: false
    property var guidance: provider ? provider.guidance : ({})
    property bool navigating: guidance.state === "active"
    property bool mapMode: provider ? provider.mapAvailable : false
    property var mapState: mapMode ? provider.mapState : ({})
    property bool browserAvailable: !!provider && provider.mapBrowser.page !== undefined
    property bool panelOpen: false
    signal activated()
    radius: 22
    color: palette.card
    clip: true

    function configureMap() {
        if (!visible || !provider || !mapMode || width <= 0 || height <= 0) return
        var scale = Math.min(1, 1280 / Math.max(width, height))
        provider.configureMap(Math.round(width * scale), Math.round(height * scale))
    }
    onWidthChanged: configureMap()
    onHeightChanged: configureMap()
    onVisibleChanged: { configureMap(); if (!visible) panelOpen = false }
    onNavigatingChanged: if (navigating && panelOpen) { provider.mapBrowse("close"); panelOpen = false }
    onMapModeChanged: configureMap()
    onProviderChanged: configureMap()
    Component.onCompleted: configureMap()

    MapCanvas {
        id: canvas
        objectName: "navigationMapCanvas"
        anchors.fill: parent
        visible: mapMode
        provider: card.provider
        MouseArea {
            anchors.fill: parent
            enabled: !compact && mapMode && !panelOpen
            onPressed: canvas.touch("press", mouse.x, mouse.y)
            onPositionChanged: if (pressed) canvas.touch("move", mouse.x, mouse.y)
            onReleased: canvas.touch("release", mouse.x, mouse.y)
            onCanceled: canvas.touch("cancel", 0, 0)
        }
    }

    Rectangle {
        id: mapToolbar
        objectName: "navigationMapToolbar"
        x: 16; y: 16; width: parent.width - 32; height: 62; radius: 14
        color: palette.card; opacity: 0.96
        visible: mapMode && !compact && browserAvailable && !panelOpen
        Rectangle {
            objectName: "navigationDestinationButton"
            x: 6; y: 6; width: navigating ? 64 : Math.min(300, parent.width - 92); height: 50
            radius: 10; color: palette.button
            Text {
                anchors.centerIn: parent; width: parent.width - 16; horizontalAlignment: Text.AlignHCenter
                text: navigating ? (provider.mapBrowser.voiceEnabled ? "♪" : "♫") : qsTranslate("Sailplay", "Choose destination")
                textFormat: Text.PlainText; color: palette.text; font.pixelSize: 26; elide: Text.ElideRight
            }
            MouseArea {
                anchors.fill: parent; enabled: !!provider && !provider.mapBrowseBusy
                onClicked: {
                    if (navigating) provider.mapBrowse("mute")
                    else { panelOpen = true; provider.mapBrowse("history") }
                }
            }
        }
        Rectangle {
            anchors.right: parent.right; anchors.rightMargin: 6; y: 6
            width: navigating ? Math.min(230, parent.width * 0.45) : 64; height: 50; radius: 10; color: palette.button
            Text {
                anchors.centerIn: parent; width: parent.width - 12; horizontalAlignment: Text.AlignHCenter
                text: navigating ? qsTranslate("Sailplay", "Stop navigation") : "⚙"
                color: palette.text; font.pixelSize: 26; elide: Text.ElideRight
            }
            MouseArea {
                anchors.fill: parent; enabled: !!provider && !provider.mapBrowseBusy
                onClicked: {
                    if (navigating) provider.stopNavigation()
                    else { panelOpen = true; provider.mapBrowse("settings") }
                }
            }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 16
        anchors.topMargin: mapToolbar.visible ? 92 : 16
        width: Math.max(0, parent.width - (compact ? 32 : 112))
        height: mapStatus.height + 24
        radius: 14
        color: palette.card
        opacity: 0.93
        visible: mapMode && !panelOpen && (navigating || !provider.mapReady || provider.error)
        Text {
            id: mapStatus
            anchors.centerIn: parent
            width: parent.width - 24
            text: navigating ? card.symbol(guidance.maneuver || "unknown") + "  "
                  + card.distance(guidance.nextDistanceMeters || 0) + "  " + (guidance.nextRoad || "")
                  : ((provider ? provider.error : "") || qsTranslate("Sailplay", "Loading map"))
            color: palette.text
            font.pixelSize: compact ? 24 : 30
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }

    Column {
        id: mapControls
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 16
        anchors.topMargin: mapToolbar.visible ? 92 : 16
        spacing: 12
        property real buttonSize: Math.max(44, Math.min(68, (card.height - (mapToolbar.visible ? 92 : 16)
            - (routePreview.visible ? routePreview.height + 32 : 16) - 24) / 3))
        visible: mapMode && !compact
        Repeater {
            model: [{label: "◎", command: "position"}, {label: "+", command: "zoom-in"}, {label: "−", command: "zoom-out"}]
            Rectangle {
                width: mapControls.buttonSize
                height: mapControls.buttonSize
                radius: 14
                color: palette.card
                opacity: 0.93
                Text { anchors.centerIn: parent; text: modelData.label; color: palette.text; font.pixelSize: 38 }
                MouseArea { anchors.fill: parent; onClicked: provider.mapControl(modelData.command) }
            }
        }
    }

    Rectangle {
        id: routePreview
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 16
        height: Math.max(58, routeText.height) + 24
        radius: 14
        color: palette.card
        opacity: 0.93
        visible: mapMode && !compact && !panelOpen && (navigating || !!mapState.place || !!mapState.building || !!mapState.built || !!mapState.error)
        Text {
            id: routeText
            x: 12
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, parent.width - routeAction.width - (bookmarkPlace.visible ? 140 : clearPlace.visible ? 88 : 36))
            text: navigating ? qsTranslate("Sailplay", "%1 min").arg(Math.ceil((guidance.remainingSeconds || 0) / 60))
                  + " · " + card.distance(guidance.remainingDistanceMeters || 0)
                  : (mapState.error || mapState.summary || mapState.place || qsTranslate("Sailplay", "Building route"))
            color: palette.text
            font.pixelSize: 26
            maximumLineCount: 2
            wrapMode: Text.WordWrap
            elide: Text.ElideRight
        }
        Rectangle {
            id: routeAction
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.rightMargin: bookmarkPlace.visible ? 116 : clearPlace.visible ? 64 : 12
            width: Math.min(230, parent.width * 0.45)
            height: 58
            radius: 12
            color: palette.dock
            visible: navigating || !!mapState.canStart || (!!mapState.place && !mapState.building)
            Text {
                anchors.centerIn: parent
                width: parent.width - 12
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                font.pixelSize: 24
                color: palette.text
                text: navigating ? qsTranslate("Sailplay", "Stop navigation")
                    : (mapState.canStart ? qsTranslate("Sailplay", "Start navigation") : qsTranslate("Sailplay", "Route here"))
            }
            MouseArea {
                anchors.fill: parent
                onClicked: {
                    if (navigating) provider.stopNavigation()
                    else provider.mapControl(mapState.canStart ? "start" : "route-to-place")
                }
            }
        }
        Rectangle {
            id: bookmarkPlace
            anchors.right: clearPlace.left; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
            width: 44; height: 58; radius: 12; color: palette.dock; visible: clearPlace.visible && !!mapState.place
            Text { anchors.centerIn: parent; text: mapState.bookmarked ? "★" : "☆"; color: palette.text; font.pixelSize: 30 }
            MouseArea { anchors.fill: parent; onClicked: provider.mapBrowse("toggle-bookmark") }
        }
        Rectangle {
            id: clearPlace
            objectName: "navigationPreviewCloseButton"
            anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
            width: 44; height: 58; radius: 12; color: palette.dock
            visible: browserAvailable && !navigating && (!!mapState.place || !!mapState.building || !!mapState.built || !!mapState.error)
            Text { anchors.centerIn: parent; text: "×"; color: palette.text; font.pixelSize: 30 }
            MouseArea {
                anchors.fill: parent
                onClicked: {
                    if (mapState.building || mapState.built || mapState.error) provider.stopNavigation()
                    else provider.mapBrowse("clear-place")
                }
            }
        }
    }

    MapDestinationPanel {
        id: destinationPanel
        objectName: "navigationDestinationPanel"
        x: 16; y: 16
        width: Math.max(0, Math.min(card.width - 112, Math.max(360, card.width * 0.36)))
        height: Math.max(0, card.height - 32)
        provider: card.provider; palette: card.palette; navigating: card.navigating
        visible: card.panelOpen && !compact && mapMode
        onDismissed: card.panelOpen = false
    }

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
        visible: !mapMode
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
