import QtQuick 2.0
import org.nemomobile.grilo 0.1 as Grilo
import "/usr/lib64/qt5/qml/com/jolla/mediaplayer/AudioTrackerHelpers.js" as AudioTrackerHelpers

Grilo.GriloModel {
    id: library
    signal resolved(string uri)
    source: Grilo.GriloQuery {
        id: query
        source: "grl-tracker3-source"
        count: 1
        query: AudioTrackerHelpers.getSongsQuery("", {"unknownArtist":"", "unknownAlbum":""})
        registry: Grilo.GriloRegistry {
            Component.onCompleted: loadPluginById("grl-tracker3")
        }
        onAvailableChanged: if (available) refresh()
        onFinished: library.resolved(library.count ? String(library.get(0).url) : "")
    }
    property Timer timeout: Timer { interval: 8000; running: true; onTriggered: library.resolved("") }
}
