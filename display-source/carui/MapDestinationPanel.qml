import QtQuick 2.0

Rectangle {
    id: panel
    property var provider
    property var palette
    property bool navigating: false
    property var browser: provider ? provider.mapBrowser : ({})
    property string page: browser.page || "history"
    property bool busy: !provider || provider.mapBrowseBusy
    signal dismissed()
    radius: 18
    color: palette.card
    clip: true

    function openPage(name) {
        searchDelay.stop()
        searchInput.focus = false
        Qt.inputMethod.hide()
        provider.mapBrowse(name)
    }
    function closePanel() {
        openPage("close")
        dismissed()
    }
    function search() {
        if (busy) { searchDelay.restart(); return }
        provider.mapBrowse("search", {query: searchInput.text.trim()})
    }
    onPageChanged: {
        list.positionViewAtBeginning()
        if (page === "search" && !searchInput.activeFocus) searchInput.text = browser.query || ""
    }
    onVisibleChanged: if (!visible) { searchDelay.stop(); searchInput.focus = false; Qt.inputMethod.hide() }
    MouseArea { anchors.fill: parent }

    Row {
        id: heading
        x: 12; y: 12; width: parent.width - 24; height: 58; spacing: 10
        Rectangle {
            width: 54; height: parent.height; radius: 12; color: palette.button
            Text { anchors.centerIn: parent; text: "‹"; color: palette.text; font.pixelSize: 40 }
            MouseArea {
                anchors.fill: parent
                enabled: !busy
                onClicked: {
                    if (page === "bookmarks") panel.openPage("bookmark-groups")
                    else if (page !== "history" && page !== "settings") panel.openPage("history")
                    else panel.closePanel()
                }
            }
        }
        Text {
            width: heading.width - 118; height: parent.height
            verticalAlignment: Text.AlignVCenter; color: palette.text; font.pixelSize: 28
            textFormat: Text.PlainText; elide: Text.ElideRight
            text: page === "bookmarks" ? browser.title || qsTranslate("Sailplay", "Bookmarks")
                : page === "bookmark-groups" ? qsTranslate("Sailplay", "Bookmarks")
                : page === "settings" ? qsTranslate("Sailplay", "Map settings")
                : page === "categories" ? qsTranslate("Sailplay", "Nearby places")
                : page === "search" ? qsTranslate("Sailplay", "Search")
                : qsTranslate("Sailplay", "Choose destination")
        }
        Rectangle {
            width: 54; height: parent.height; radius: 12; color: palette.button
            Text { anchors.centerIn: parent; text: "×"; color: palette.text; font.pixelSize: 36 }
            MouseArea { anchors.fill: parent; onClicked: panel.closePanel() }
        }
    }
    Row {
        id: tabs
        x: 12; y: heading.y + heading.height + 10; width: parent.width - 24
        height: visible ? 56 : 0; spacing: 8; visible: page !== "settings"
        Repeater {
            model: [
                {label: qsTranslate("Sailplay", "Recent"), command: "history"},
                {label: qsTranslate("Sailplay", "Search"), command: "categories"},
                {label: qsTranslate("Sailplay", "Bookmarks"), command: "bookmark-groups"}
            ]
            Rectangle {
                width: (tabs.width - 16) / 3; height: tabs.height; radius: 12
                color: page === modelData.command || (page === "search" && index === 1)
                    || (page === "bookmarks" && index === 2) ? palette.notice : palette.button
                Text { anchors.centerIn: parent; width: parent.width - 12; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: modelData.label; color: palette.text; font.pixelSize: 24 }
                MouseArea { anchors.fill: parent; enabled: !busy; onClicked: panel.openPage(modelData.command) }
            }
        }
    }
    Rectangle {
        id: searchBox
        x: 12; y: tabs.y + tabs.height + 10; width: parent.width - 24
        height: visible ? 58 : 0; radius: 12; color: palette.button
        visible: page === "search" || page === "categories"
        TextInput {
            id: searchInput
            objectName: "navigationSearchInput"
            x: 14; width: parent.width - 82; height: parent.height
            color: palette.text; font.pixelSize: 26; verticalAlignment: TextInput.AlignVCenter
            maximumLength: 256; selectByMouse: true; clip: true
            onActiveFocusChanged: if (activeFocus && panel.visible) Qt.inputMethod.show()
            onTextChanged: if (activeFocus) searchDelay.restart()
            onAccepted: { searchDelay.stop(); panel.search(); focus = false; Qt.inputMethod.hide() }
            Text {
                anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                text: qsTranslate("Sailplay", "Search places or addresses"); color: palette.secondary; font.pixelSize: 24
                elide: Text.ElideRight; visible: searchInput.text === "" && !searchInput.activeFocus
            }
        }
        Rectangle {
            anchors.right: parent.right; width: 62; height: parent.height; radius: 12; color: palette.button
            Text { anchors.centerIn: parent; text: "⌕"; color: palette.text; font.pixelSize: 34 }
            MouseArea { anchors.fill: parent; onClicked: { searchDelay.stop(); panel.search(); searchInput.focus = false; Qt.inputMethod.hide() } }
        }
    }
    Timer { id: searchDelay; interval: 300; onTriggered: panel.search() }
    Text {
        id: status
        x: 16; y: searchBox.y + searchBox.height + 8; width: parent.width - 32
        height: visible ? 60 : 0; color: palette.secondary; font.pixelSize: 24
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
        text: provider && provider.error ? provider.error : busy ? qsTranslate("Sailplay", "Loading")
            : browser.searching ? qsTranslate("Sailplay", "Searching")
            : page === "settings" ? ""
            : !browser.rows || !browser.rows.length ? (page === "history" ? qsTranslate("Sailplay", "No recent searches")
                : page === "bookmark-groups" || page === "bookmarks" ? qsTranslate("Sailplay", "No bookmarks")
                : qsTranslate("Sailplay", "No results")) : ""
        visible: text !== ""
    }
    ListView {
        id: list
        objectName: "navigationDestinationList"
        x: 12; y: status.y + status.height + 8; width: parent.width - 24
        height: Math.max(0, pagination.y - y - 8); clip: true; spacing: 8
        boundsBehavior: Flickable.StopAtBounds; visible: page !== "settings"
        model: browser.rows || []
        delegate: Rectangle {
            width: list.width; height: 86; radius: 12; color: rowTouch.pressed ? palette.notice : palette.button
            Column {
                x: 14; width: parent.width - 48; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                Text { width: parent.width; text: modelData.title; textFormat: Text.PlainText; color: palette.text; font.pixelSize: 27; elide: Text.ElideRight }
                Text { width: parent.width; text: modelData.kind === "group" ? qsTranslate("Sailplay", "%1 places").arg(modelData.subtitle) : modelData.subtitle; textFormat: Text.PlainText; color: palette.secondary; font.pixelSize: 21; elide: Text.ElideRight; visible: text !== "" }
            }
            Text { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; text: "›"; color: palette.secondary; font.pixelSize: 30 }
            MouseArea {
                id: rowTouch; anchors.fill: parent; enabled: !busy && !browser.searching
                onClicked: { searchInput.focus = false; Qt.inputMethod.hide(); provider.mapBrowse("select", {id: modelData.id}) }
            }
        }
    }
    Row {
        id: pagination
        x: 12; y: panel.height - height - 12; width: panel.width - 24; spacing: 8
        height: visible ? 54 : 0; visible: !!browser.previous || !!browser.next
        Repeater {
            model: [{label: qsTranslate("Sailplay", "Previous"), command: "previous"}, {label: qsTranslate("Sailplay", "Next"), command: "next"}]
            Rectangle {
                width: (pagination.width - 8) / 2; height: pagination.height; radius: 12; color: palette.button
                opacity: browser[modelData.command] ? 1 : 0.4
                Text { anchors.centerIn: parent; text: modelData.label; color: palette.text; font.pixelSize: 24 }
                MouseArea { anchors.fill: parent; enabled: !busy && !!browser[modelData.command]; onClicked: provider.mapBrowse(modelData.command) }
            }
        }
    }
    Flickable {
        x: 12; y: tabs.y + 12; width: parent.width - 24
        height: Math.max(0, panel.height - y - 12); clip: true; visible: page === "settings"
        contentWidth: width; contentHeight: settingsColumn.height; boundsBehavior: Flickable.StopAtBounds
        Column {
        id: settingsColumn
        width: parent.width; spacing: 10
        Text { width: parent.width; text: qsTranslate("Sailplay", "Route type"); color: palette.secondary; font.pixelSize: 24 }
        Repeater {
            model: [{label: qsTranslate("Sailplay", "Driving"), command: "vehicle"}, {label: qsTranslate("Sailplay", "Walking"), command: "walking"}, {label: qsTranslate("Sailplay", "Cycling"), command: "cycling"}]
            Rectangle {
                width: parent.width; height: 58; radius: 12; color: browser.routerType === index ? palette.notice : palette.button
                opacity: navigating ? 0.5 : 1
                Text { anchors.centerIn: parent; text: modelData.label; color: palette.text; font.pixelSize: 26 }
                MouseArea { anchors.fill: parent; enabled: !busy && !navigating; onClicked: provider.mapBrowse(modelData.command) }
            }
        }
        Rectangle {
            width: parent.width; height: 58; radius: 12; color: palette.button; opacity: browser.voiceAvailable ? 1 : 0.5
            Text { anchors.centerIn: parent; text: browser.voiceEnabled ? qsTranslate("Sailplay", "Mute guidance") : qsTranslate("Sailplay", "Enable guidance voice"); color: palette.text; font.pixelSize: 24 }
            MouseArea { anchors.fill: parent; enabled: !busy && !!browser.voiceAvailable; onClicked: provider.mapBrowse("mute") }
        }
        }
    }
    Connections {
        target: provider
        onMapBrowserChanged: {
            if (!searchInput.activeFocus && provider.mapBrowser.page === "search")
                searchInput.text = provider.mapBrowser.query || ""
            if (panel.visible && !provider.mapBrowseBusy && provider.mapBrowser.page === "") {
                searchDelay.stop(); searchInput.focus = false; Qt.inputMethod.hide(); panel.dismissed()
            }
        }
    }
}
