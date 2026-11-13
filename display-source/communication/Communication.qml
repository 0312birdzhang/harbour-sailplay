import QtQuick 2.0
import QtQuick.Window 2.0
import "../carui" as CarUi

Window {
    id: window
    visible: true
    width: 1280
    height: 720
    color: palette.background
    title: phoneApp ? "Sailplay Phone" : "Sailplay Messages"
    property bool composing: false
    property var pending: 0
    property string notice: ""
    property string replyAccount: ""
    readonly property bool smsReply: !replyAccount || replyAccount.indexOf("/ring/tel") >= 0
    readonly property bool canSend: phoneApp || !smsReply || communicationState.smsAvailable === true
    property bool pickingRecipient: false
    property var calls: communicationState.calls || []
    property alias colors: palette
    QtObject {
        id: palette
        property color background: "#142638"
        property color card: "#1c3349"
        property color button: "#284760"
        property color notice: "#426985"
        property color text: "#ffffff"
        property color secondary: "#b5c4d1"
    }
    function submit(action, parameters) {
        if (!renderer.ready || pending) return
        pending = renderer.invoke(action, parameters)
        notice = ""
    }
    Connections {
        target: renderer
        onRequestFinished: {
            if (requestId !== window.pending) return
            window.pending = 0
            if (window.pickingRecipient) {
                window.pickingRecipient = false
                if (errorName) { window.notice = errorMessage; return }
                recipient.text = result.number
                window.replyAccount = result.account
                window.composing = true
                return
            }
            window.notice = errorName ? errorMessage : qsTranslate("Sailplay", "Request submitted")
            if (!errorName && !phoneApp) {
                message.text = ""
                window.composing = false
            }
        }
        onErrorOccurred: { window.pending = 0; window.pickingRecipient = false; window.notice = message }
    }
    Item {
        id: content
        anchors.fill: parent
        anchors.margins: 20
        anchors.bottomMargin: 20 + (Qt.inputMethod.visible ? Math.min(window.height / 2, Qt.inputMethod.keyboardRectangle.height) : 0)
        Row {
            id: toolbar
            width: parent.width
            height: 60
            spacing: 12
            Text {
                width: Math.max(0, toolbar.width - 260)
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: phoneApp ? qsTranslate("Sailplay", "Phone") : qsTranslate("Sailplay", "Messages")
                color: palette.text
                font.pixelSize: 32
            }
            Rectangle {
                width: 248; height: parent.height; radius: 12; color: palette.button
                Text {
                    anchors.centerIn: parent; color: palette.text; font.pixelSize: 26
                    text: window.composing ? qsTranslate("Sailplay", "Browse")
                          : phoneApp ? qsTranslate("Sailplay", "Dial pad") : qsTranslate("Sailplay", "New message")
                }
                MouseArea { anchors.fill: parent; onClicked: { window.replyAccount = ""; window.composing = !window.composing } }
            }
        }
        Flickable {
            id: callPanel
            y: toolbar.height + 12
            width: parent.width
            height: Math.min(callBar.height, content.height / 3)
            contentHeight: callBar.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: callBar
                width: callPanel.width
                spacing: 8
                Repeater {
                    model: phoneApp ? window.calls : []
                    Rectangle {
                        width: callBar.width; height: 70; radius: 12; color: palette.card
                        Text {
                            x: 16; width: Math.max(0, parent.width - 400); height: parent.height
                            verticalAlignment: Text.AlignVCenter; color: palette.text; font.pixelSize: 26
                            text: modelData.number + "  " + modelData.status; elide: Text.ElideRight
                        }
                        Row {
                            anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                            Rectangle {
                                width: 160; height: 54; radius: 10; color: "#28774e"; visible: modelData.incoming
                                Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Answer"); color: palette.text; font.pixelSize: 24 }
                                MouseArea { anchors.fill: parent; enabled: !window.pending; onClicked: window.submit("phone.answer", {id: modelData.id}) }
                            }
                            Rectangle {
                                width: 160; height: 54; radius: 10; color: "#963b48"
                                Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Hang up"); color: palette.text; font.pixelSize: 24 }
                                MouseArea { anchors.fill: parent; enabled: !window.pending; onClicked: window.submit("phone.hangup", {id: modelData.id}) }
                            }
                        }
                    }
                }
                Rectangle {
                    width: callBar.width; height: visible ? 54 : 0; radius: 10; color: palette.button
                    visible: phoneApp && window.calls.length > 0
                    Text { anchors.centerIn: parent; text: communicationState.muted ? qsTranslate("Sailplay", "Unmute microphone") : qsTranslate("Sailplay", "Mute microphone"); color: palette.text; font.pixelSize: 24 }
                    MouseArea { anchors.fill: parent; enabled: !window.pending; onClicked: window.submit("phone.mute", {muted: !communicationState.muted}) }
                }
            }
        }
        CarUi.ContentPage {
            x: 0; y: callPanel.y + callPanel.height + 12
            width: parent.width; height: Math.max(0, footer.y - y - 12)
            palette: window.colors
            provider: browser
            visible: !window.composing && (phoneApp || (browser.page.id || "").indexOf("thread:") !== 0)
        }
        MessageReader {
            x: 0; y: callPanel.y + callPanel.height + 12
            width: parent.width; height: Math.max(0, footer.y - y - 12)
            palette: window.colors; provider: browser
            visible: !window.composing && !phoneApp && (browser.page.id || "").indexOf("thread:") === 0
            onReply: {
                if (window.pending || !renderer.ready) return
                window.pickingRecipient = true
                window.submit("messages.recipient", {id: browser.page.id})
            }
        }
        Flickable {
            id: composer
            x: 0; y: callPanel.y + callPanel.height + 12
            width: parent.width
            height: Math.max(0, footer.y - y - 12)
            contentHeight: form.height
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            visible: window.composing
            Column {
                id: form
                width: composer.width
                spacing: 12
                Rectangle {
                    width: parent.width; height: 64; radius: 12; color: palette.card
                    TextInput {
                        id: recipient
                        objectName: "communicationRecipient"
                        anchors.fill: parent; anchors.margins: 14
                        color: palette.text; font.pixelSize: 30; verticalAlignment: TextInput.AlignVCenter
                        maximumLength: 64; inputMethodHints: Qt.ImhDialableCharactersOnly; clip: true
                        Text { anchors.fill: parent; verticalAlignment: Text.AlignVCenter; color: palette.secondary; font.pixelSize: 26; visible: recipient.text === ""; text: qsTranslate("Sailplay", "Phone number") }
                    }
                }
                Grid {
                    width: parent.width; columns: 3; spacing: 8; visible: phoneApp
                    Repeater {
                        model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"]
                        Rectangle {
                            width: (composer.width - 16) / 3
                            height: Math.max(40, Math.min(70, (composer.height - 158) / 4 - 8))
                            radius: 10; color: touch.pressed ? palette.notice : palette.button
                            Text { anchors.centerIn: parent; text: modelData; color: palette.text; font.pixelSize: 30 }
                            MouseArea {
                                id: touch
                                property bool held: false
                                anchors.fill: parent
                                onPressed: held = false
                                onClicked: if (!held) recipient.insert(recipient.cursorPosition, modelData)
                                onPressAndHold: {
                                    if (modelData === "0") {
                                        held = true
                                        recipient.insert(recipient.cursorPosition, "+")
                                    }
                                }
                            }
                        }
                    }
                }
                Rectangle {
                    width: parent.width; height: Math.max(70, composer.height - 148); radius: 12; color: palette.card
                    visible: !phoneApp
                    Flickable {
                        anchors.fill: parent; anchors.margins: 14
                        contentHeight: Math.max(height, message.paintedHeight); clip: true
                        TextEdit {
                            id: message
                            objectName: "communicationMessage"
                            width: parent.width; height: Math.max(parent.height, paintedHeight)
                            color: palette.text; font.pixelSize: 28; wrapMode: TextEdit.Wrap
                            Text { color: palette.secondary; visible: message.text === ""; text: qsTranslate("Sailplay", "Message"); font.pixelSize: 26 }
                        }
                    }
                }
                Row {
                    width: parent.width; height: 60; spacing: 12
                    Rectangle {
                        width: (parent.width - 12) / 2; height: parent.height; radius: 12; color: palette.button
                        Text { anchors.centerIn: parent; text: phoneApp ? "⌫" : qsTranslate("Sailplay", "Clear"); color: palette.text; font.pixelSize: 28 }
                        MouseArea { anchors.fill: parent; onClicked: { if (phoneApp) recipient.text = recipient.text.slice(0, -1); else message.text = "" } }
                    }
                    Rectangle {
                        width: (parent.width - 12) / 2; height: parent.height; radius: 12; color: "#28774e"
                        opacity: renderer.ready && !window.pending && window.canSend ? 1 : 0.5
                        Text { anchors.centerIn: parent; text: phoneApp ? qsTranslate("Sailplay", "Call") : qsTranslate("Sailplay", "Send"); color: palette.text; font.pixelSize: 28 }
                        MouseArea {
                            anchors.fill: parent; enabled: renderer.ready && !window.pending && window.canSend
                            onClicked: window.submit(phoneApp ? "phone.dial" : "messages.send",
                                phoneApp ? {number: recipient.text.trim()} : {number: recipient.text.trim(), message: message.text, account: window.replyAccount})
                        }
                    }
                }
            }
        }
        Text {
            id: footer
            x: 0; y: parent.height - height; width: parent.width; height: 40
            color: palette.secondary; font.pixelSize: 22; elide: Text.ElideRight
            text: window.notice || browser.error || (renderer.ready
                ? (!phoneApp && window.smsReply ? communicationState.smsError || "" : "")
                : qsTranslate("Sailplay", "Connecting"))
        }
    }
}
