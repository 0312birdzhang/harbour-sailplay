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

    Item {
        id: mapToolbar
        objectName: "navigationMapToolbar"
        x: 16; y: 16; width: destinationButton.width + (bookmarksButton.visible ? bookmarksButton.width + 8 : 0); height: 56
        visible: mapMode && !compact && browserAvailable && !panelOpen
        MouseArea { anchors.fill: parent }
        Rectangle {
            id: destinationButton
            objectName: "navigationDestinationButton"
            width: navigating ? 56 : Math.max(0, Math.min(264, card.width - 176)); height: parent.height
            radius: 14; color: destinationTouch.pressed ? palette.pressed : palette.card
            Text {
                anchors.centerIn: parent; width: parent.width - 16; horizontalAlignment: Text.AlignHCenter
                text: navigating ? (provider.mapBrowser.voiceEnabled ? "♪" : "♫") : qsTranslate("Sailplay", "Choose destination")
                textFormat: Text.PlainText; color: palette.text; font.pixelSize: 24; elide: Text.ElideRight
            }
            MouseArea {
                id: destinationTouch
                anchors.fill: parent; enabled: !!provider && !provider.mapBrowseBusy
                onClicked: {
                    if (navigating) provider.mapBrowse("mute")
                    else { panelOpen = true; provider.mapBrowse("history") }
                }
            }
        }
        Rectangle {
            id: bookmarksButton
            objectName: "navigationBookmarksButton"
            x: destinationButton.width + 8; width: 56; height: parent.height
            radius: 14; color: bookmarksTouch.pressed ? palette.pressed : palette.card
            visible: !navigating
            MapBookmarkIcon { objectName: "navigationBookmarksIcon"; anchors.centerIn: parent; width: 28; height: 28; ink: palette.text; filled: true }
            MouseArea {
                id: bookmarksTouch
                anchors.fill: parent; enabled: !!provider && !provider.mapBrowseBusy
                onClicked: { panelOpen = true; provider.mapBrowse("bookmark-groups") }
            }
        }
    }

    Rectangle {
        id: mapSettings
        objectName: "navigationSettingsButton"
        anchors.right: parent.right; anchors.rightMargin: 16; y: 16
        width: navigating ? Math.min(216, card.width * 0.4) : 56; height: 56
        radius: 14; color: settingsTouch.pressed ? palette.pressed : palette.card
        visible: mapToolbar.visible
        MouseArea { anchors.fill: parent }
        Text {
            anchors.centerIn: parent; width: parent.width - 12; horizontalAlignment: Text.AlignHCenter
            text: navigating ? qsTranslate("Sailplay", "Stop navigation") : "⚙"
            color: palette.text; font.pixelSize: 24; elide: Text.ElideRight
        }
        MouseArea {
            id: settingsTouch
            anchors.fill: parent; enabled: !!provider && !provider.mapBrowseBusy
            onClicked: {
                if (navigating) provider.stopNavigation()
                else { panelOpen = true; provider.mapBrowse("settings") }
            }
        }
    }

    Rectangle {
        objectName: "navigationMapStatus"
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 16
        anchors.topMargin: mapToolbar.visible ? 84 : 16
        width: Math.max(0, Math.min(parent.width - (compact ? 32 : 112), navigating ? 440 : 360))
        height: mapStatus.height + 24
        radius: 14
        color: palette.card
        opacity: 0.93
        visible: mapMode && !panelOpen && (navigating || !provider.mapReady || provider.error)
        MouseArea { anchors.fill: parent; enabled: !compact }
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
        anchors.topMargin: mapSettings.visible ? 84 : 16
        spacing: 12
        property real buttonSize: Math.max(44, Math.min(68, (card.height - (mapSettings.visible ? 84 : 16)
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
        objectName: "navigationRoutePreview"
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 16
        width: Math.max(0, Math.min(card.width - 32, navigating ? 280 : 560))
        height: routeText.height + (previewActions.visible ? 92 : 32)
        radius: 14
        color: palette.card
        opacity: 0.93
        visible: mapMode && !compact && !panelOpen && (navigating || !!mapState.place || !!mapState.building || !!mapState.built || !!mapState.error)
        MouseArea { objectName: "navigationPreviewShield"; anchors.fill: parent }
        Text {
            id: routeText
            objectName: "navigationPreviewText"
            x: 16; y: 16
            width: Math.max(0, parent.width - 32)
            text: navigating ? qsTranslate("Sailplay", "%1 min").arg(Math.ceil((guidance.remainingSeconds || 0) / 60))
                  + " · " + card.distance(guidance.remainingDistanceMeters || 0)
                  : (mapState.error || mapState.summary || mapState.place || qsTranslate("Sailplay", "Building route"))
            color: palette.text
            font.pixelSize: 24
            maximumLineCount: 2
            wrapMode: Text.WordWrap
            elide: Text.ElideRight
        }
        Row {
            id: previewActions
            x: 16; y: routeText.y + routeText.height + 12; width: parent.width - 32; height: 52; spacing: 8
            visible: !navigating
            Rectangle {
                id: routeAction
                objectName: "navigationRouteActionButton"
                width: Math.max(0, Math.min(260, previewActions.width - (bookmarkPlace.visible ? 120 : clearPlace.visible ? 60 : 0)))
                height: parent.height
                radius: 12
                color: routeTouch.pressed ? "#206a38" : "#268344"
                visible: !!mapState.canStart || (!!mapState.place && !mapState.building)
                Text {
                    anchors.centerIn: parent
                    width: parent.width - 12
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    font.pixelSize: 24
                    color: "white"
                    text: mapState.canStart ? qsTranslate("Sailplay", "Start navigation") : qsTranslate("Sailplay", "Route here")
                }
                MouseArea {
                    id: routeTouch
                    anchors.fill: parent
                    enabled: !!provider && !provider.mapBrowseBusy
                    onClicked: provider.mapControl(mapState.canStart ? "start" : "route-to-place")
                }
            }
            Rectangle {
                id: bookmarkPlace
                objectName: "navigationBookmarkPlaceButton"
                width: 52; height: parent.height; radius: 12; color: bookmarkTouch.pressed ? palette.pressed : palette.button
                visible: clearPlace.visible && !!mapState.place
                MapBookmarkIcon { objectName: "navigationBookmarkPlaceIcon"; anchors.centerIn: parent; width: 28; height: 28; ink: palette.text; filled: !!mapState.bookmarked }
                MouseArea { id: bookmarkTouch; anchors.fill: parent; enabled: !!provider && !provider.mapBrowseBusy; onClicked: provider.mapBrowse("toggle-bookmark") }
            }
            Rectangle {
                id: clearPlace
                objectName: "navigationPreviewCloseButton"
                width: 52; height: parent.height; radius: 12; color: clearTouch.pressed ? palette.pressed : palette.button
                visible: browserAvailable && !navigating && (!!mapState.place || !!mapState.building || !!mapState.built || !!mapState.error)
                Text { anchors.centerIn: parent; text: "×"; color: palette.text; font.pixelSize: 30 }
                MouseArea {
                    id: clearTouch
                    anchors.fill: parent
                    enabled: !!provider && !provider.mapBrowseBusy
                    onClicked: {
                        if (mapState.building || mapState.built || mapState.error) provider.stopNavigation()
                        else provider.mapBrowse("clear-place")
                    }
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
