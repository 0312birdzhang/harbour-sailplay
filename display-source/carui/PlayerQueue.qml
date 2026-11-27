import QtQuick 2.0

Rectangle {
    id: panel
    objectName: "playerQueue"
    property var palette
    property string service
    property var items: []
    property int currentIndex: -1
    property string revision: ""
    property bool loading: false
    property bool failed: false
    property bool playingItem: false
    property bool playing: false
    signal closed()
    // musicCard, which hosts this panel, already draws the surface.
    radius: 22; color: "transparent"
    onVisibleChanged: if(visible)refresh()
    onServiceChanged: {items=[];revision="";currentIndex=-1;playingItem=false;if(visible)refresh()}
    function refresh() {
        if(!service)return
        loading=!items.length
        carController.requestPlayerQueue(service)
    }
    Timer {interval:3000;repeat:true;running:panel.visible;onTriggered:panel.refresh()}
    Connections {
        target: carController
        onPlayerQueueAvailable: {
            if(service!==panel.service)return
            panel.loading=loading;panel.failed=error
            if(!error && panel.revision!==revision)panel.items=items
            panel.currentIndex=index;panel.revision=revision
        }
        onPlayerPlaybackFinished: {
            if(service===panel.service){panel.playingItem=false;panel.refresh()}
        }
    }
    MouseArea { anchors.fill:parent }
    Rectangle {
        x:16;y:16;width:88;height:88;radius:14
        color: backTouch.pressed
            ? Qt.rgba(panel.palette.highlightColor.r, panel.palette.highlightColor.g, panel.palette.highlightColor.b, 0.3)
            : Qt.rgba(panel.palette.highlightBackgroundColor.r, panel.palette.highlightBackgroundColor.g, panel.palette.highlightBackgroundColor.b, 0.55)
        Image {
            anchors.centerIn: parent; width: parent.width * 0.62; height: width
            source: "image://theme/icon-m-back?" + (backTouch.pressed ? panel.palette.highlightColor : panel.palette.primaryColor)
        }
        MouseArea { id: backTouch; anchors.fill: parent; onClicked: panel.closed() }
    }
    Text {
        x:120;y:16;width:parent.width-x-24;height:88;verticalAlignment:Text.AlignVCenter
        text:qsTranslate("Sailplay","Play queue (%1)").arg(panel.items.length)
        color:palette.highlightColor;font.pixelSize:34;font.weight:Font.Light;elide:Text.ElideRight
    }
    ListView {
        id: list
        objectName: "queueSongs"
        x:16;y:120;width:parent.width-32;height:parent.height-y-16
        clip:true;model:panel.items;spacing:6
        delegate: Rectangle {
            width:list.width;height:82;radius:12
            color:index===panel.currentIndex ? panel.palette.button : "transparent"
            Text {x:16;y:12;width:parent.width-48;font.pixelSize:27
                color:index===panel.currentIndex ? panel.palette.highlightColor : panel.palette.text
                text:(index===panel.currentIndex ? (panel.playing ? "▶ " : "• ") : "")+modelData.title;textFormat:Text.PlainText;elide:Text.ElideRight}
            Text {x:16;y:48;width:parent.width-48;font.pixelSize:21
                color:index===panel.currentIndex ? panel.palette.secondaryHighlightColor : panel.palette.secondary
                text:modelData.artist;textFormat:Text.PlainText;elide:Text.ElideRight}
            MouseArea {
                anchors.fill:parent;enabled:!panel.playingItem && !panel.failed && panel.revision.length===64
                onClicked: {
                    panel.playingItem=true
                    carController.playQueueItem(panel.service,modelData.index,modelData.key,panel.revision)
                }
            }
        }
    }
    Text {
        anchors.centerIn:parent;width:parent.width-64;horizontalAlignment:Text.AlignHCenter
        visible:!panel.items.length;color:palette.secondary;font.pixelSize:28;wrapMode:Text.Wrap
        text:panel.loading ? qsTranslate("Sailplay","Loading…") : panel.failed ? qsTranslate("Sailplay","Queue unavailable") : qsTranslate("Sailplay","Queue is empty")
    }
}
