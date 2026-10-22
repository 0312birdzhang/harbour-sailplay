// Run through carui on a test session with a configured dashboard map.
import QtQuick 2.0
import QtQuick.Window 2.0

Window {
    visible: false
    function check(label, dashboard, music, app, origin) {
        if (carController.dashboardActive !== dashboard || carController.musicActive !== music
                || carController.currentApp !== app || carController.returnToDashboard !== origin) {
            console.log("RETURN_FAIL", label, carController.dashboardActive,
                        carController.musicActive, carController.currentApp, carController.returnToDashboard)
            return false
        }
        console.log("RETURN_OK", label)
        return true
    }
    Timer {
        interval: 400; running: true
        onTriggered: {
            var map = carController.dashboardMapApp
            if (!map) { console.log("RETURN_FAIL", "no map configured"); Qt.quit(); return }
            carController.openDashboard()
            carController.openMusic()
            carController.homeClicked()
            if (!check("dashboard -> music -> dashboard", true, false, "", true)) { Qt.quit(); return }
            carController.dockClicked(map)
            if (!check("dashboard -> map", false, false, map, true)) { Qt.quit(); return }
            carController.homeClicked()
            if (!check("dashboard -> map -> dashboard", true, false, "", true)) { Qt.quit(); return }
            carController.homeClicked()
            if (!check("dashboard -> apps", false, false, "", false)) { Qt.quit(); return }
            carController.openMusic()
            carController.homeClicked()
            if (!check("apps -> music -> apps", false, false, "", false)) { Qt.quit(); return }
            carController.dockClicked(map)
            if (!check("apps -> map", false, false, map, false)) { Qt.quit(); return }
            carController.homeClicked()
            if (!check("apps -> map -> apps", false, false, "", false)) { Qt.quit(); return }
            carController.openDashboard()
            carController.dockClicked(map)
            carController.openMusic()
            carController.homeClicked()
            if (!check("dashboard -> map -> music -> dashboard", true, false, "", true)) { Qt.quit(); return }
            carController.openMusic()
            carController.dockClicked(map)
            carController.homeClicked()
            if (!check("dashboard -> music -> map -> dashboard", true, false, "", true)) { Qt.quit(); return }
            carController.homeClicked()
            carController.openMusic()
            carController.dockClicked(map)
            carController.homeClicked()
            if (!check("apps -> music -> map -> apps", false, false, "", false)) { Qt.quit(); return }
            console.log("RETURN_INTEGRATION_PASS")
            Qt.quit()
        }
    }
    Timer { interval: 10000; running: true; onTriggered: { console.log("RETURN_FAIL", "timeout"); Qt.quit() } }
}
