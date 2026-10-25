import QtQuick 2.6
import Sailfish.Silica 1.0
import "file:///usr/share/organicmaps/qml/pages" as Maps
ApplicationWindow {
    property int silicaWidth: Screen.width
    property int silicaHeight: Screen.height
    property int pageWidth: pageStack.currentPage ? pageStack.currentPage.width : 0
    property int pageHeight: pageStack.currentPage ? pageStack.currentPage.height : 0
    property QtObject appInfo: QtObject {
        property bool voiceSupported: false
        function localized(key) { return key }
    }
    property var guidance: ({speed:"80",speedUnits:"公里每小时",hoursLeft:0,
        minutesLeft:5,minuteUnits:"分钟",arrival:"18:30",distanceLeftValue:"2.8",
        distanceLeftUnits:"公里",distanceToTurn:"200 米",turnIcon:"ic_turn_left.webp",
        street:"荔新公路",streetParts:[{text:"荔新公路"}],progress:.3})
    allowedOrientations: Orientation.Landscape
    cover: null
    initialPage: Component {
        Page {
            id: page
            allowedOrientations: Orientation.Landscape
            readonly property real navigationScale: Math.max(.1,Math.min(1,height/(480*Theme.pixelRatio),width/(800*Theme.pixelRatio)))
            Rectangle { anchors.fill: parent; color:"#263249" }
            Maps.NavigationTopPanel {
                id: topPanel
                x: Theme.paddingMedium; y: Theme.paddingMedium
                width: (parent.width-2*x)/scale
                scale: page.navigationScale
                transformOrigin: Item.TopLeft
                navigation: guidance
                androidDp: Theme.pixelRatio*2.625/1.5
                landscape: true
            }
            Maps.NavigationBottomPanel {
                id: bottomPanel
                anchors.left: parent.left; anchors.bottom: parent.bottom
                width: Math.round(parent.width*.4)/scale
                scale: page.navigationScale
                transformOrigin: Item.BottomLeft
                navigation: guidance
                androidDp: Theme.pixelRatio*2.625/1.5
                routing: QtObject { property bool voiceAvailable: false; property bool voiceEnabled:false }
            }
            function check(item) {
                if (!item.visible) return
                var watched=["80","公里每小时","5","分钟","18:30","2.8","公里","200 米"]
                if (watched.indexOf(item.text)>=0) {
                    var p=item.mapToItem(page,0,0)
                    var q=item.mapToItem(page,item.width,item.height)
                    if (p.x < -1 || p.y < -1 || q.x > page.width+1 || q.y > page.height+1)
                        throw new Error("NAV_BOUNDS_FAIL "+item.text+" "+p.x+","+p.y+" "+q.x+","+q.y+" page "+page.width+","+page.height)
                }
                for (var i=0;i<item.children.length;i++)check(item.children[i])
            }
            Timer { interval:300;running:true;repeat:true;onTriggered:{
                try {page.check(topPanel);page.check(bottomPanel);console.log("NAV_BOUNDS_OK",page.width,page.height,page.navigationScale)}
                catch(e){console.log(e);Qt.quit()}
            } }
        }
    }
}
