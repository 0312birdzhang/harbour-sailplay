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
        property int backCount: 0
        function detailAction(id) { activated = id }
        function back() { backCount++; canGoBack = false }
    }
    property int returnCount: 0
    ContentPage {
        id: page; anchors.fill: parent; provider: contentProvider; palette: colors
        onReturnRequested: parent.returnCount++
    }
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
            var back = find(page, "contentBack")
            if (!action || !touch || !list || action.width <= 0 || action.height <= 0
                || list.y + list.height > action.parent.y) {
                console.log("CONTENT_CONTROLS_FAIL geometry", stage); Qt.quit(); return
            }
            if (stage === 0) {
                if (!back || back.visible) { console.log("CONTENT_CONTROLS_FAIL ordinary root back"); Qt.quit(); return }
                touch.clicked(null)
                if (contentProvider.activated !== "all") { console.log("CONTENT_CONTROLS_FAIL routing"); Qt.quit(); return }
                contentProvider.busy = true
            } else if (stage === 1) {
                if (touch.enabled) { console.log("CONTENT_CONTROLS_FAIL busy"); Qt.quit(); return }
                contentProvider.busy = false
                contentProvider.detail = {title:"Episodes", items:[], actions:[{id:"all",title:"Play all",enabled:false}]}
                parent.width = 580
            } else if (stage === 2) {
                if (touch.enabled) { console.log("CONTENT_CONTROLS_FAIL disabled"); Qt.quit(); return }
                page.canReturn = true
            } else if (stage === 3) {
                if (!back.visible || !back.item || back.width <= 0) { console.log("CONTENT_CONTROLS_FAIL music root back"); Qt.quit(); return }
                back.item.clicked()
                if (parent.returnCount !== 1 || contentProvider.backCount !== 0) { console.log("CONTENT_CONTROLS_FAIL music return routing"); Qt.quit(); return }
                contentProvider.canGoBack = true
            } else if (stage === 4) {
                back.item.clicked()
                if (parent.returnCount !== 1 || contentProvider.backCount !== 1) { console.log("CONTENT_CONTROLS_FAIL nested back routing"); Qt.quit(); return }
            } else if (stage === 5) {
                if (!back.visible) { console.log("CONTENT_CONTROLS_FAIL back missing after root"); Qt.quit(); return }
                back.item.clicked()
                if (parent.returnCount !== 2) { console.log("CONTENT_CONTROLS_FAIL return after nested"); Qt.quit(); return }
                page.canReturn = false
            } else {
                if (back.visible) { console.log("CONTENT_CONTROLS_FAIL back remains on ordinary root"); Qt.quit(); return }
                console.log("CONTENT_CONTROLS_PASS routing busy disabled geometry music-return nested-back"); Qt.quit(); return
            }
            stage++
        }
    }
}
