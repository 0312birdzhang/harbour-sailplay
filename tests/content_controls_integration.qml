import QtQuick 2.0

Item {
    width: 1140; height: 688
    QtObject { id: carController; property bool dayTheme: false }
    CarPalette { id: colors }
    QtObject {
        id: contentProvider
        property bool ready: true
        property bool busy: false
        property bool canGoBack: false
        property string name: "Content test"
        property string error: ""
        property string layout: "split"
        property var tabs: []
        property var side: ({})
        property var items: []
        property string currentItem: "folder"
        property var page: ({title:"Library", actions:[], hasMore:false})
        property var detail: ({title:"Episodes", items:[], actions:[{id:"all",title:"Play all",enabled:true}]})
        property string activated: ""
        function detailAction(id) { activated = id }
    }
    ContentPage { id: page; anchors.fill: parent; provider: contentProvider; palette: colors }
    function find(root, name) {
        if (root.objectName === name) return root
        for (var i = 0; i < root.children.length; i++) {
            var item = find(root.children[i], name)
            if (item) return item
        }
        return null
    }
    Timer {
        interval: 100; repeat: true; running: true
        property int stage: 0
        onTriggered: {
            var action = find(page, "contentDetailAction")
            var touch = find(page, "contentDetailActionTouch")
            var list = find(page, "contentDetailList")
            if (!action || !touch || !list || action.width <= 0 || action.height <= 0
                || list.y + list.height > action.parent.y) {
                console.log("CONTENT_CONTROLS_FAIL geometry", stage); Qt.quit(); return
            }
            if (stage === 0) {
                touch.clicked(null)
                if (contentProvider.activated !== "all") { console.log("CONTENT_CONTROLS_FAIL routing"); Qt.quit(); return }
                contentProvider.busy = true
            } else if (stage === 1) {
                if (touch.enabled) { console.log("CONTENT_CONTROLS_FAIL busy"); Qt.quit(); return }
                contentProvider.busy = false
                contentProvider.detail = {title:"Episodes", items:[], actions:[{id:"all",title:"Play all",enabled:false}]}
                parent.width = 580
            } else {
                if (touch.enabled) { console.log("CONTENT_CONTROLS_FAIL disabled"); Qt.quit(); return }
                console.log("CONTENT_CONTROLS_PASS routing busy disabled geometry"); Qt.quit(); return
            }
            stage++
        }
    }
}
