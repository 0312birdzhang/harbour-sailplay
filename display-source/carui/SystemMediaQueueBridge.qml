import QtQuick 2.0
import Nemo.DBus 2.0
import org.nemomobile.grilo 0.1 as Grilo
import com.jolla.mediaplayer 1.0
import "/usr/lib64/qt5/qml/com/jolla/mediaplayer/AudioTrackerHelpers.js" as AudioTrackerHelpers

Item {
    id: bridge
    visible: false
    property bool ready: false
    function song(model,index) {
        return typeof model.get === "function" ? model.get(index) : model.getMediaItem(index)
    }
    function rows(model) {
        var result=[]
        for(var i=0;i<Math.min(model.count,10000);++i) {
            var item=song(model,i)
            result.push({uri:String(item.url),title:item.title || "",artist:item.author || "",duration:item.duration || 0})
        }
        return result
    }
    function snapshot() {
        var queue=AudioPlayer.playModel
        var items=[]
        if(queue.count && queueRows.count===queue.count) {
            for(var i=0;i<queueRows.count;++i)items.push(queueRows.itemAt(i).value)
        } else items=rows(library)
        return JSON.stringify({ready:ready,items:items,index:queue.count ? queue.currentIndex : -1,
            libraryCount:library.count,queueCount:queue.count})
    }
    Repeater {
        id: queueRows
        model: AudioPlayer.playModel
        delegate: Item {
            visible: false
            property var value: ({uri:String(model.media.url),title:model.media.title || "",
                artist:model.media.author || "",duration:model.media.duration || 0})
        }
    }
    function prepare() {
        if(!AudioPlayer.playModel.count && library.count) {
            AudioPlayer.playModel.setModel(library)
            AudioPlayer.playModel.currentIndex=0
            app.dockedPanel().open=true
        }
    }
    function playIndex(index) {
        var queue=AudioPlayer.playModel
        var count=queue.count || library.count
        if(!ready || index<0 || index>=count || index!==Math.floor(index))return false
        if(!queue.count)AudioPlayer.play(library,index)
        else AudioPlayer.playIndex(index)
        app.dockedPanel().open=true
        return true
    }
    Grilo.GriloModel {
        id: library
        source: Grilo.GriloQuery {
            source: "grl-tracker3-source"
            count: 10000
            query: AudioTrackerHelpers.getSongsQuery("", {"unknownArtist":"", "unknownAlbum":""})
            registry: Grilo.GriloRegistry { Component.onCompleted: loadPluginById("grl-tracker3") }
            onAvailableChanged: if(available)refresh()
            onFinished: { bridge.ready=true; bridge.prepare() }
        }
    }
    DBusAdaptor {
        service: "com.jolla.mediaplayer"
        path: "/com/jolla/mediaplayer/sailplay"
        iface: "com.jolla.mediaplayer.sailplay"
        function snapshot() { return bridge.snapshot() }
        function playIndex(index) { return bridge.playIndex(Number(index)) }
    }
}
