import QtQuick 2.0
import Sailplay 1.0
import "NavigationGuidance.js" as Guidance

Rectangle {
    id: card
    property var provider
    property var palette
    property bool compact: false
    property var guidance: provider ? provider.guidance : ({})
    readonly property bool navigating: !!provider && provider.navigating
    readonly property bool guidanceAvailable: navigating && provider.ready && guidance.state === "active"
    readonly property var lastGuidance: provider && provider.lastGuidance ? provider.lastGuidance : ({})
    readonly property bool showGuidance: guidanceAvailable || (navigating && !!lastGuidance && lastGuidance.state === "active")
    readonly property var displayGuidance: guidanceAvailable ? guidance : (showGuidance ? lastGuidance : ({}))
    property bool mapMode: provider ? provider.mapAvailable : false
    property var mapState: mapMode ? provider.mapState : ({})
    property bool browserAvailable: !!provider && provider.mapBrowser.page !== undefined
    property bool panelOpen: false
    // Size the controls in the assigned map viewport, independently of the map frame resolution.
    readonly property real controlsScale: compact ? 1 : Math.max(0.5, Math.min(width / 1000, height / 480))
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
    onNavigatingChanged: { if (navigating && panelOpen) { provider.mapBrowse("close"); panelOpen = false } }
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
        id: mapOverlay
        objectName: "navigationMapOverlay"
        width: card.width / card.controlsScale
        height: card.height / card.controlsScale
        scale: card.controlsScale
        transformOrigin: Item.TopLeft

        Item {
            id: mapToolbar
            objectName: "navigationMapToolbar"
            x: 16; y: 16; width: destinationButton.width + (bookmarksButton.visible ? bookmarksButton.width + 12 : 0); height: 76
            visible: mapMode && !compact && browserAvailable && !panelOpen
            MouseArea { anchors.fill: parent }
            Rectangle {
                id: destinationButton
                objectName: "navigationDestinationButton"
                width: navigating ? 76 : Math.max(0, Math.min(280, mapOverlay.width - 208)); height: parent.height
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
                x: destinationButton.width + 12; width: 76; height: parent.height
                radius: 14; color: bookmarksTouch.pressed ? palette.pressed : palette.card
                visible: !navigating
                MapBookmarkIcon { objectName: "navigationBookmarksIcon"; anchors.centerIn: parent; width: 36; height: 36; ink: palette.text; filled: true }
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
            width: navigating ? Math.min(240, mapOverlay.width * 0.4) : 76; height: 76
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
            id: mapGuidanceBanner
            objectName: "navigationMapStatus"
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.margins: 16
            anchors.topMargin: mapToolbar.visible ? mapToolbar.y + mapToolbar.height + 16 : 16
            width: Math.max(0, Math.min(parent.width - (compact ? 32 : 124), navigating ? 440 : 360))
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
                text: showGuidance ? card.symbol(displayGuidance.maneuver || "unknown") + "  "
                      + card.distance(displayGuidance.nextDistanceMeters || 0) + "  " + (displayGuidance.nextRoad || "")
                      : navigating ? card.statusText()
                      : ((provider ? provider.error : "") || qsTranslate("Sailplay", "Loading map"))
                color: palette.text
                font.pixelSize: compact ? 24 : 30
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }

        Rectangle {
            id: speedLimitBadge
            objectName: "navigationSpeedLimit"
            readonly property int limitKmh: showGuidance && displayGuidance.speedLimitMps > 0
                ? Math.round(displayGuidance.speedLimitMps * 3.6) : 0
            readonly property bool speeding: limitKmh > 0 && displayGuidance.speedMps > displayGuidance.speedLimitMps + 0.5
            visible: mapMode && !panelOpen && limitKmh > 0
            anchors.left: mapGuidanceBanner.right
            anchors.verticalCenter: mapGuidanceBanner.verticalCenter
            anchors.leftMargin: 12
            width: compact ? 64 : 76; height: width; radius: width / 2
            color: speeding ? "#d93025" : "#ffffff"
            border.color: "#d93025"; border.width: compact ? 5 : 6
            Text {
                anchors.centerIn: parent
                text: speedLimitBadge.limitKmh
                color: speedLimitBadge.speeding ? "#ffffff" : "#111111"
                font.pixelSize: compact ? 24 : 30; font.bold: true
            }
        }

        Rectangle {
            id: laneGuidanceBar
            objectName: "navigationLaneGuidance"
            readonly property var lanes: showGuidance && displayGuidance.lanes ? displayGuidance.lanes : []
            visible: mapMode && !panelOpen && lanes.length > 0
            anchors.left: mapGuidanceBanner.left
            anchors.top: mapGuidanceBanner.bottom
            anchors.topMargin: 8
            width: Math.min(mapGuidanceBanner.width, laneRow.implicitWidth + 24)
            height: compact ? 44 : 52; radius: 12
            color: palette.card; opacity: 0.93
            function laneArrow(lane) {
                var dirs = lane && lane.directions ? lane.directions : []
                var d = dirs.length ? String(dirs[0]).toLowerCase() : "straight"
                if (d.indexOf("uturn") >= 0) return "↺"
                if (d.indexOf("slight-left") >= 0) return "↖"
                if (d.indexOf("slight-right") >= 0) return "↗"
                if (d.indexOf("left") >= 0) return "←"
                if (d.indexOf("right") >= 0) return "→"
                return "↑"
            }
            Row {
                id: laneRow
                anchors.centerIn: parent; spacing: 10
                Repeater {
                    model: laneGuidanceBar.lanes
                    Text {
                        text: laneGuidanceBar.laneArrow(modelData)
                        color: modelData && modelData.active ? palette.highlightColor : palette.secondary
                        opacity: modelData && modelData.active ? 1.0 : 0.45
                        font.pixelSize: compact ? 26 : 32; font.bold: !!(modelData && modelData.active)
                    }
                }
            }
        }

        Column {
            id: mapControls
            objectName: "navigationMapControls"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 16
            anchors.topMargin: mapSettings.visible ? mapSettings.y + mapSettings.height + 16 : 16
            spacing: 12
            // The preview only reserves vertical space when it reaches the right-hand controls.
            readonly property real bottomInset: routePreview.visible && routePreview.x + routePreview.width + 12 > x
                ? routePreview.height + 32 : 16
            readonly property real buttonSize: Math.max(0, Math.min(76,
                (mapOverlay.height - y - bottomInset - 2 * spacing) / 3))
            visible: mapMode && !compact
            property bool headingUp: navigating
            function positionLabel() {
                var mode = mapState && mapState.positionMode ? String(mapState.positionMode).toLowerCase() : ""
                if (mode === "follow-and-rotate" || mode === "heading") return "▲"
                if (mode === "follow" || mode === "north") return "N↑"
                if (mode === "not-follow" || mode === "pending") return "◎"
                return headingUp ? "▲" : "N↑"
            }
            function positionHighlighted() {
                var mode = mapState && mapState.positionMode ? String(mapState.positionMode).toLowerCase() : ""
                if (mode === "follow-and-rotate" || mode === "heading") return true
                if (mode === "follow" || mode === "north" || mode === "not-follow" || mode === "pending") return false
                return headingUp
            }
            Repeater {
                model: [{label: "position", command: "position"}, {label: "+", command: "zoom-in"}, {label: "−", command: "zoom-out"}]
                Rectangle {
                    objectName: "navigationMapControl_" + modelData.command
                    width: mapControls.buttonSize
                    height: mapControls.buttonSize
                    radius: 14
                    color: palette.card
                    opacity: 0.93
                    Text {
                        anchors.centerIn: parent
                        text: modelData.command === "position" ? mapControls.positionLabel() : modelData.label
                        color: modelData.command === "position" && mapControls.positionHighlighted() ? palette.highlightColor : palette.text
                        font.pixelSize: modelData.command === "position" ? 30 : 38
                        font.bold: modelData.command === "position"
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            if (modelData.command === "position") mapControls.headingUp = !mapControls.headingUp
                            provider.mapControl(modelData.command)
                        }
                    }
                }
            }
        }

        Rectangle {
            id: routePreview
            objectName: "navigationRoutePreview"
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.margins: 16
            width: Math.max(0, Math.min(mapOverlay.width - 32, navigating ? 340 : 480))
            height: routeText.height + (alternateRoutesRow.visible ? alternateRoutesRow.height + 12 : 0)
                + (previewActions.visible ? 120 : alongRouteRow.visible ? alongRouteRow.height + 44 : 32)
            radius: 14
            color: palette.card
            opacity: 0.93
            visible: mapMode && !compact && !panelOpen && (showGuidance || (!navigating
                && (!!mapState.place || !!mapState.building || !!mapState.built || !!mapState.error)))
            MouseArea { objectName: "navigationPreviewShield"; anchors.fill: parent }
            Text {
                id: routeText
                objectName: "navigationPreviewText"
                x: 16; y: 16
                width: Math.max(0, parent.width - 32)
                text: navigating ? qsTranslate("Sailplay", "%1 min").arg(Math.ceil((displayGuidance.remainingSeconds || 0) / 60))
                      + " · " + card.distance(displayGuidance.remainingDistanceMeters || 0)
                      : (mapState.error || mapState.summary || mapState.place || qsTranslate("Sailplay", "Building route"))
                color: palette.text
                font.pixelSize: 24
                maximumLineCount: 2
                wrapMode: Text.WordWrap
                elide: Text.ElideRight
            }
            Row {
                id: alternateRoutesRow
                objectName: "navigationAlternateRoutes"
                readonly property var routes: !navigating && mapState.routes ? mapState.routes : []
                visible: routes.length > 1
                x: 16; y: routeText.y + routeText.height + 8
                width: parent.width - 32; height: visible ? 44 : 0; spacing: 8
                Repeater {
                    model: alternateRoutesRow.routes.slice(0, 3)
                    Rectangle {
                        width: Math.max(0, (alternateRoutesRow.width - alternateRoutesRow.spacing * (Math.min(3, alternateRoutesRow.routes.length) - 1)) / Math.min(3, alternateRoutesRow.routes.length))
                        height: 44; radius: 10
                        color: modelData && modelData.selected ? palette.accent : palette.button
                        Text {
                            anchors.centerIn: parent; width: parent.width - 12
                            horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                            text: modelData && modelData.summary ? modelData.summary : ("#" + (index + 1))
                            color: modelData && modelData.selected ? "#ffffff" : palette.text
                            font.pixelSize: 18; font.bold: !!(modelData && modelData.selected)
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: if (modelData && modelData.id !== undefined) provider.mapBrowse("selectRoute", {id: String(modelData.id)})
                        }
                    }
                }
            }
            Row {
                id: alongRouteRow
                objectName: "navigationAlongRouteActions"
                visible: navigating && browserAvailable
                x: 16; y: routeText.y + routeText.height + 10
                width: parent.width - 32; height: visible ? 48 : 0; spacing: 8
                Repeater {
                    model: [{label: "⛽", category: "fuel"}, {label: "⚡", category: "charging"}, {label: "P", category: "parking"}]
                    Rectangle {
                        width: Math.max(0, (alongRouteRow.width - alongRouteRow.spacing * 2) / 3)
                        height: 48; radius: 10; color: palette.button
                        Text { anchors.centerIn: parent; text: modelData.label; color: palette.text; font.pixelSize: 22; font.bold: true }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: { panelOpen = true; provider.mapBrowse("alongRoute", {category: modelData.category}) }
                        }
                    }
                }
            }
            Row {
                id: previewActions
                x: 16; y: (alternateRoutesRow.visible ? alternateRoutesRow.y + alternateRoutesRow.height : routeText.y + routeText.height) + 12; width: parent.width - 32; height: 76; spacing: 12
                visible: !navigating
                Rectangle {
                    id: routeAction
                    objectName: "navigationRouteActionButton"
                    width: Math.max(0, Math.min(280, previewActions.width - (bookmarkPlace.visible ? 176 : clearPlace.visible ? 88 : 0)))
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
                    width: 76; height: parent.height; radius: 12; color: bookmarkTouch.pressed ? palette.pressed : palette.button
                    visible: clearPlace.visible && !!mapState.place
                    MapBookmarkIcon { objectName: "navigationBookmarkPlaceIcon"; anchors.centerIn: parent; width: 36; height: 36; ink: palette.text; filled: !!mapState.bookmarked }
                    MouseArea { id: bookmarkTouch; anchors.fill: parent; enabled: !!provider && !provider.mapBrowseBusy; onClicked: provider.mapBrowse("toggle-bookmark") }
                }
                Rectangle {
                    id: clearPlace
                    objectName: "navigationPreviewCloseButton"
                    width: 76; height: parent.height; radius: 12; color: clearTouch.pressed ? palette.pressed : palette.button
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

        Rectangle {
            id: speedBadge
            objectName: "navigationSpeedBadge"
            anchors.left: routePreview.visible ? routePreview.right : parent.left
            anchors.leftMargin: routePreview.visible ? 12 : 16
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 16
            readonly property real speedMps: displayGuidance.speedMps !== undefined ? displayGuidance.speedMps : -1
            readonly property real speedLimitMps: displayGuidance.speedLimitMps !== undefined ? displayGuidance.speedLimitMps : -1
            readonly property bool hasSpeed: speedMps >= 0
            readonly property bool hasLimit: speedLimitMps > 0
            readonly property bool exceeded: hasSpeed && hasLimit && speedMps > speedLimitMps
            visible: mapMode && !compact && !panelOpen && showGuidance && (hasSpeed || hasLimit)
            height: Math.max(64, routePreview.visible ? routePreview.height : 64)
            width: speedRow.width + 28
            radius: 14
            color: palette.card
            opacity: 0.93
            MouseArea { anchors.fill: parent }
            Row {
                id: speedRow
                anchors.centerIn: parent
                spacing: 12
                Row {
                    visible: speedBadge.hasSpeed
                    spacing: 4
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        objectName: "navigationSpeedValue"
                        text: speedBadge.hasSpeed ? String(Guidance.speedKmh(speedBadge.speedMps)) : ""
                        color: speedBadge.exceeded ? "#e53935" : palette.text
                        font.pixelSize: 28
                        font.bold: true
                        anchors.baseline: speedUnit.baseline
                    }
                    Text {
                        id: speedUnit
                        text: "km/h"
                        color: palette.secondary
                        font.pixelSize: 18
                    }
                }
                Rectangle {
                    objectName: "navigationSpeedLimit"
                    visible: speedBadge.hasLimit
                    width: 44; height: 44; radius: 22
                    anchors.verticalCenter: parent.verticalCenter
                    color: "white"
                    border.color: "#d32f2f"
                    border.width: 4
                    Text {
                        anchors.centerIn: parent
                        text: speedBadge.hasLimit ? String(Guidance.speedKmh(speedBadge.speedLimitMps)) : ""
                        color: "#111111"
                        font.pixelSize: 18
                        font.bold: true
                    }
                }
            }
        }

        MapDestinationPanel {
            id: destinationPanel
            objectName: "navigationDestinationPanel"
            x: 16; y: 16
            width: Math.max(0, Math.min(mapOverlay.width - 124, Math.max(420, mapOverlay.width * 0.42)))
            height: Math.max(0, mapOverlay.height - 32)
            provider: card.provider; palette: card.palette; navigating: card.navigating
            visible: card.panelOpen && !compact && mapMode
            onDismissed: card.panelOpen = false
        }
    }

    function distance(meters) {
        return Guidance.distance(meters)
    }
    function symbol(maneuver) {
        return Guidance.symbol(maneuver, displayGuidance.drivingSide, displayGuidance.exitNumber)
    }
    function statusText() {
        if (provider && provider.error) return provider.error
        if (!provider || !provider.ready) return qsTranslate("Sailplay", "Connecting navigation")
        var states = {
            "idle": qsTranslate("Sailplay", "Ready for navigation"),
            "unavailable": qsTranslate("Sailplay", "Waiting for navigation updates"),
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
            visible: showGuidance
            text: card.symbol(displayGuidance.maneuver || "unknown")
            color: palette.text
            font.pixelSize: compact ? 78 : 108
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            visible: showGuidance
            text: card.distance(displayGuidance.nextDistanceMeters || 0)
            color: palette.text
            font.pixelSize: compact ? 34 : 44
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            width: parent.width
            text: showGuidance ? (displayGuidance.nextRoad || displayGuidance.currentRoad || "") : card.statusText()
            color: palette.text
            font.pixelSize: compact ? 26 : 34
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            maximumLineCount: compact ? 2 : 3
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            visible: showGuidance
            text: qsTranslate("Sailplay", "%1 min").arg(Math.ceil((displayGuidance.remainingSeconds || 0) / 60))
                  + " · " + card.distance(displayGuidance.remainingDistanceMeters || 0)
            color: palette.secondary
            font.pixelSize: compact ? 24 : 28
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
        Rectangle {
            visible: !compact && navigating && provider.ready
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
