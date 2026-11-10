import QtQuick 2.0
import QtQuick.Window 2.0

Window {
    id: window
    visible: false
    width: 1920
    height: 720
    property int ticks: 0
    property bool hidden: false

    function fail(reason) {
        console.log("MUSIC_SDK_UI_FAIL " + reason)
        Qt.quit()
    }
    Component.onCompleted: {
        if (!carController.ensureMusicBackend("harbour-mconnect")) {
            fail("compatibility activation")
            return
        }
        if (carController.lastMusicApp !== "harbour-mconnect-silica") {
            fail("compatibility desktop identity")
            return
        }
        carController.dockClicked("harbour-mconnect-silica")
        if (!carController.musicActive || carController.currentApp.length) fail("music entry")
    }
    Timer {
        interval: 500
        running: true
        repeat: true
        onTriggered: {
            ++window.ticks
            if (carController.musicError.length) {
                window.fail(carController.musicError)
                stop()
                return
            }
            if (!window.hidden) {
                if (carController.preferredMusicService(["org.mpris.MediaPlayer2.harbour_mconnect"]).length === 0) {
                    if (window.ticks > 20) { window.fail("MPRIS activation timeout"); stop() }
                    return
                }
                carController.homeClicked()
                window.hidden = true
                window.ticks = 0
                if (carController.musicActive) { window.fail("hidden activity"); stop(); return }
                console.log("MUSIC_SDK_UI_HIDDEN_LEASE")
                return
            }
            if (window.ticks < 28) return
            if (carController.preferredMusicService(["org.mpris.MediaPlayer2.harbour_mconnect"]).length === 0) {
                window.fail("hidden lease retention")
                stop()
                return
            }
            if (!carController.ensureMusicBackend("harbour-mconnect-silica")) {
                window.fail("running player reuse")
                stop()
                return
            }
            console.log("MUSIC_SDK_UI_PASS compatibility-identity dock-entry MPRIS-reuse hidden-lease")
            stop()
        }
    }
}
