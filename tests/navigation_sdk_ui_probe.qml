import QtQuick 2.0
import QtQuick.Window 2.0
import "file:///opt/sailplay/carui" as SailplayUi

Window {
    id: window
    visible: false
    width: 1920
    height: 720
    property string applicationId: Qt.application.arguments[4]
    property int phase: 0
    property var sizes: [[1920, 720], [1280, 720], [720, 1280]]

    SailplayUi.CarPalette { id: carPalette }
    SailplayUi.NavigationCard {
        id: card
        x: 16
        y: 16
        width: window.width - 32
        height: window.height - 32
        provider: carController.navigation
        palette: carPalette
    }
    Component.onCompleted: {
        var ids = []
        var entries = carController.dockApps
        for (var i = 0; i < entries.length; ++i) ids.push(entries[i].appId)
        console.log("NAVIGATION_UI_RECENT_BASE " + JSON.stringify(ids))
        carController.dockClicked(applicationId)
    }
    Timer {
        interval: 100
        running: true
        repeat: true
        onTriggered: {
            if (!carController.navigation.ready || card.guidance.state !== "active") return
            if (!carController.navigationActive || carController.currentApp !== window.applicationId
                    || card.children[0].height <= 0 || card.children[0].width <= 0
                    || card.children[0].height > card.height || card.children[0].width > card.width) {
                console.log("NAVIGATION_UI_ENTRY_FAIL " + JSON.stringify({
                    phase: window.phase, contentWidth: card.children[0].width,
                    contentHeight: card.children[0].height, cardWidth: card.width,
                    cardHeight: card.height
                }))
                stop()
                return
            }
            window.phase += 1
            if (window.phase === window.sizes.length) {
                console.log("NAVIGATION_UI_ENTRY_PASS " + JSON.stringify({
                    applicationId: window.applicationId, layouts: window.phase,
                    maneuver: card.guidance.maneuver, nextRoad: card.guidance.nextRoad
                }))
                stop()
                return
            }
            window.width = window.sizes[window.phase][0]
            window.height = window.sizes[window.phase][1]
            card.compact = window.phase === 1
        }
    }
}
