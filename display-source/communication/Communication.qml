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
    readonly property real uiScale: Math.max(0.65, Math.min(width / 1280, height / 720))
    readonly property real gap: 12 * uiScale
    CarUi.CarPalette {
        id: palette
        day: dayTheme
        ambience: followAmbience
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
        anchors.margins: 20 * window.uiScale
        anchors.bottomMargin: 20 * window.uiScale + (Qt.inputMethod.visible ? Math.min(window.height / 2, Qt.inputMethod.keyboardRectangle.height) : 0)
        Row {
            id: toolbar
            width: parent.width
            height: 60 * window.uiScale
            spacing: window.gap
            Text {
                width: Math.max(0, toolbar.width - toolbarAction.width - toolbar.spacing)
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: phoneApp ? qsTranslate("Sailplay", "Phone") : qsTranslate("Sailplay", "Messages")
                color: palette.text
                font.pixelSize: 32 * window.uiScale
            }
            Rectangle {
                id: toolbarAction
                width: Math.min(248 * window.uiScale, toolbar.width * 0.35); height: parent.height; radius: 12; color: palette.button
                Text {
                    anchors.centerIn: parent; width: parent.width - 16 * window.uiScale
                    horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                    color: palette.text; font.pixelSize: 26 * window.uiScale
                    text: window.composing ? qsTranslate("Sailplay", "Browse")
                          : phoneApp ? qsTranslate("Sailplay", "Dial pad") : qsTranslate("Sailplay", "New message")
                }
                MouseArea { anchors.fill: parent; onClicked: { window.replyAccount = ""; window.composing = !window.composing } }
            }
        }
        Flickable {
            id: callPanel
            y: toolbar.height + window.gap
            width: parent.width
            height: phoneApp && window.calls.length ? Math.min(callBar.height, content.height / 3) : 0
            contentHeight: callBar.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: callBar
                width: callPanel.width
                spacing: 8 * window.uiScale
                Repeater {
                    model: phoneApp ? window.calls : []
                    Rectangle {
                        width: callBar.width; height: 70 * window.uiScale; radius: 12; color: palette.card
                        Text {
                            x: 16 * window.uiScale; width: Math.max(0, callActions.x - x - window.gap); height: parent.height
                            verticalAlignment: Text.AlignVCenter; color: palette.text; font.pixelSize: 26 * window.uiScale
                            text: modelData.number + "  " + modelData.status; elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                        Row {
                            id: callActions
                            anchors.right: parent.right; anchors.rightMargin: window.gap; anchors.verticalCenter: parent.verticalCenter; spacing: 8 * window.uiScale
                            Rectangle {
                                width: 140 * window.uiScale; height: 54 * window.uiScale; radius: 10; color: palette.positive; visible: modelData.incoming
                                Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Answer"); color: palette.actionText; font.pixelSize: 24 * window.uiScale }
                                MouseArea { anchors.fill: parent; enabled: !window.pending; onClicked: window.submit("phone.answer", {id: modelData.id}) }
                            }
                            Rectangle {
                                width: 140 * window.uiScale; height: 54 * window.uiScale; radius: 10; color: palette.negative
                                Text { anchors.centerIn: parent; text: qsTranslate("Sailplay", "Hang up"); color: palette.actionText; font.pixelSize: 24 * window.uiScale }
                                MouseArea { anchors.fill: parent; enabled: !window.pending; onClicked: window.submit("phone.hangup", {id: modelData.id}) }
                            }
                        }
                    }
                }
                Rectangle {
                    width: callBar.width; height: visible ? 54 * window.uiScale : 0; radius: 10; color: palette.button
                    visible: phoneApp && window.calls.length > 0
                    Text { anchors.centerIn: parent; text: communicationState.muted ? qsTranslate("Sailplay", "Unmute microphone") : qsTranslate("Sailplay", "Mute microphone"); color: palette.text; font.pixelSize: 24 * window.uiScale }
                    MouseArea { anchors.fill: parent; enabled: !window.pending; onClicked: window.submit("phone.mute", {muted: !communicationState.muted}) }
                }
            }
        }
        CarUi.ContentPage {
            x: 0; y: callPanel.y + callPanel.height + (callPanel.height > 0 ? window.gap : 0)
            width: parent.width; height: Math.max(0, footer.y - y - window.gap)
            palette: window.colors
            uiScale: window.uiScale
            provider: browser
            visible: !window.composing && (phoneApp || (browser.page.id || "").indexOf("thread:") !== 0)
        }
        MessageReader {
            x: 0; y: callPanel.y + callPanel.height + (callPanel.height > 0 ? window.gap : 0)
            width: parent.width; height: Math.max(0, footer.y - y - window.gap)
            palette: window.colors; provider: browser
            uiScale: window.uiScale
            visible: !window.composing && !phoneApp && (browser.page.id || "").indexOf("thread:") === 0
            onReply: {
                if (window.pending || !renderer.ready) return
                window.pickingRecipient = true
                window.submit("messages.recipient", {id: browser.page.id})
            }
        }
        Flickable {
            id: composer
            objectName: "communicationComposer"
            x: 0; y: callPanel.y + callPanel.height + (callPanel.height > 0 ? window.gap : 0)
            width: parent.width
            height: Math.max(0, footer.y - y - window.gap)
            contentHeight: Math.max(height, form.height)
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            visible: window.composing
            Column {
                id: form
                objectName: "communicationForm"
                width: phoneApp ? Math.min(composer.width, 980 * window.uiScale) : composer.width
                x: (composer.width - width) / 2
                y: phoneApp ? Math.max(0, (composer.height - height) / 2) : 0
                spacing: window.gap
                Rectangle {
                    id: recipientBox
                    width: parent.width; height: 76 * window.uiScale; radius: 12; color: palette.card
                    TextInput {
                        id: recipient
                        objectName: "communicationRecipient"
                        anchors.fill: parent; anchors.margins: 14 * window.uiScale
                        color: palette.text; font.pixelSize: 34 * window.uiScale; verticalAlignment: TextInput.AlignVCenter
                        horizontalAlignment: phoneApp ? TextInput.AlignHCenter : TextInput.AlignLeft
                        maximumLength: 64; inputMethodHints: Qt.ImhDialableCharactersOnly; clip: true
                        Text { anchors.fill: parent; verticalAlignment: Text.AlignVCenter; horizontalAlignment: phoneApp ? Text.AlignHCenter : Text.AlignLeft; color: palette.secondary; font.pixelSize: 26 * window.uiScale; visible: recipient.text === ""; text: qsTranslate("Sailplay", "Phone number") }
                    }
                }
                Grid {
                    id: dialGrid
                    width: parent.width; columns: 3; spacing: 8 * window.uiScale; visible: phoneApp
                    Repeater {
                        model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"]
                        Rectangle {
                            objectName: "dialKey_" + index
                            width: (dialGrid.width - 2 * dialGrid.spacing) / 3
                            height: Math.max(48 * window.uiScale, Math.min(112 * window.uiScale,
                                (composer.height - recipientBox.height - formActions.height - 2 * form.spacing - 3 * dialGrid.spacing) / 4))
                            radius: 10; color: touch.pressed ? palette.pressed : palette.button
                            Text { anchors.centerIn: parent; text: modelData; color: palette.text; font.pixelSize: 38 * window.uiScale }
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
                    width: parent.width; height: Math.max(70 * window.uiScale, composer.height - recipientBox.height - formActions.height - 2 * form.spacing); radius: 12; color: palette.card
                    visible: !phoneApp
                    Flickable {
                        anchors.fill: parent; anchors.margins: 14 * window.uiScale
                        contentHeight: Math.max(height, message.paintedHeight); clip: true
                        TextEdit {
                            id: message
                            objectName: "communicationMessage"
                            width: parent.width; height: Math.max(parent.height, paintedHeight)
                            color: palette.text; font.pixelSize: 28 * window.uiScale; wrapMode: TextEdit.Wrap
                            Text { color: palette.secondary; visible: message.text === ""; text: qsTranslate("Sailplay", "Message"); font.pixelSize: 26 * window.uiScale }
                        }
                    }
                }
                Row {
                    id: formActions
                    width: parent.width; height: 72 * window.uiScale; spacing: window.gap
                    Rectangle {
                        width: (parent.width - parent.spacing) / 2; height: parent.height; radius: 12; color: palette.button
                        Text { anchors.centerIn: parent; text: phoneApp ? "⌫" : qsTranslate("Sailplay", "Clear"); color: palette.text; font.pixelSize: 28 * window.uiScale }
                        MouseArea { anchors.fill: parent; onClicked: { if (phoneApp) recipient.text = recipient.text.slice(0, -1); else message.text = "" } }
                    }
                    Rectangle {
                        width: (parent.width - parent.spacing) / 2; height: parent.height; radius: 12; color: palette.positive
                        opacity: renderer.ready && !window.pending && window.canSend ? 1 : 0.5
                        Text { anchors.centerIn: parent; text: phoneApp ? qsTranslate("Sailplay", "Call") : qsTranslate("Sailplay", "Send"); color: palette.actionText; font.pixelSize: 28 * window.uiScale }
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
            x: 0; y: parent.height - height; width: parent.width; height: text ? 40 * window.uiScale : 0
            color: palette.secondary; font.pixelSize: 22 * window.uiScale; elide: Text.ElideRight; textFormat: Text.PlainText
            text: window.notice || browser.error || (renderer.ready
                ? (!phoneApp && window.smsReply ? communicationState.smsError || "" : "")
                : qsTranslate("Sailplay", "Connecting"))
        }
    }
}
