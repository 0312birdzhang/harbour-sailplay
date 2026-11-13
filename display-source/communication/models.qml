import QtQml 2.2
import org.nemomobile.contacts 1.0
import org.nemomobile.commhistory 1.0
import org.nemomobile.voicecall 1.0
import Sailfish.Messages 1.0
import Sailfish.Telephony 1.0
import org.nemomobile.messages.internal 1.0

QtObject {
    id: models
    signal contentChanged()
    signal messageFinished(string token, string error)
    property var pendingMessage: null
    readonly property bool messagePending: pendingMessage !== null
    property var sendChannel: null
    property QtObject channelManager: null
    property Component channelComponent: Component {
        TelepathyChannelManager { handlerName: "org.sailplay.Systemmessages" }
    }
    property QtObject simError: null
    property Component simComponent: Component {
        SimErrorState {
            multiSimManager: MessageUtils.simManager
            modemPath: MessageUtils.voiceModemPath
            onValidChanged: models.contentChanged()
            onErrorStateChanged: models.contentChanged()
        }
    }
    property QtObject sendSignals: Connections {
        target: models.sendChannel
        onSendingSucceeded: if (models.pendingMessage && eventId === models.pendingMessage.eventId) models.finishMessage("")
        onSendingFailed: if (models.pendingMessage && eventId === models.pendingMessage.eventId) models.finishMessage("Failed")
        onRequestFailed: models.finishMessage("Failed")
    }
    property QtObject sendTimer: Timer {
        interval: 15000
        onTriggered: {
            if (!models.pendingMessage) return
            // A submitted message may still reach the recipient. Keep the send guard
            // until Telepathy reports its result so a timeout cannot trigger a duplicate.
            if (models.pendingMessage.submitted)
                models.messageFinished(models.pendingMessage.token, "TimedOut")
            else models.finishMessage("Unavailable")
        }
    }
    property QtObject contacts: PeopleModel {
        filterType: PeopleModel.FilterAll
        requiredProperty: PeopleModel.PhoneNumberRequired
        onPopulatedChanged: models.contentChanged()
    }
    property QtObject history: CommCallModel {
        limit: 50
        onPopulatedChanged: models.contentChanged()
    }
    property QtObject groupManager: CommGroupManager {
        useBackgroundThread: true
        resolveContacts: true
        onModelReady: models.contentChanged()
    }
    property QtObject groups: CommContactGroupModel { manager: models.groupManager }
    property QtObject callManager: VoiceCallManager { }
    property Component conversationComponent: Component {
        CommConversationModel {
            useBackgroundThread: true
            queryMode: CommConversationModel.AsyncQuery
        }
    }

    function createConversation(id) {
        return conversationComponent.createObject(models, { groupId: id })
    }
    function calls() {
        var result = []
        for (var i = 0; i < callManager.voiceCalls.count; ++i) {
            var call = callManager.voiceCalls.instance(i)
            result.push({ id: call.handlerId, number: call.lineId, status: call.statusText,
                incoming: call.status === VoiceCall.STATUS_INCOMING || call.status === VoiceCall.STATUS_WAITING,
                provider: call.providerId })
        }
        return result
    }
    function controlCall(id, action) {
        for (var i = 0; i < callManager.voiceCalls.count; ++i) {
            var call = callManager.voiceCalls.instance(i)
            if (call.handlerId !== id) continue
            if (action === "answer") call.answer()
            else if (action === "hangup") call.hangup()
            else return false
            return true
        }
        return false
    }
    function smsAccount() { return MessageUtils.telepathyAccounts.ringAccountPath }
    function sendError(account) {
        if (!MessageUtils.messagingPermitted) return "Forbidden"
        if (MessageUtils.isSMS(account)) {
            if (!simError) simError = simComponent.createObject(models)
            if (!simError) return "Unavailable"
            if (!simError.valid || !MessageUtils.simManager.valid) return "Unavailable"
            if (simError.errorState === "noSimInserted") return "NoSim"
            if (simError.errorState === "modemDisabled") return "DisabledSim"
            if (simError.errorState === "simActivationRequired") return "LockedSim"
        }
        if (!MessageUtils.telepathyAccounts.ready) return "Unavailable"
        var selected = MessageUtils.telepathyAccounts.getAccount(account)
        return selected && selected.online ? "" : "Unavailable"
    }
    function sendMessage(request) {
        if (messagePending || sendError(request.account)) return false
        if (!channelManager) channelManager = channelComponent.createObject(models)
        if (!channelManager) return false
        sendChannel = channelManager.getConversation(request.account, request.number)
        if (!sendChannel) return false
        pendingMessage = { token: request.token, eventId: -1, submitted: false }
        sendTimer.start()
        var owner = models
        groupManager.createOutgoingMessageEvent(-1, request.account, request.number, request.message, function(eventId) {
            if (!owner.pendingMessage || owner.pendingMessage.token !== request.token) {
                if (eventId >= 0) owner.groupManager.setEventStatus(eventId, CommHistory.TemporarilyFailedStatus)
                return
            }
            owner.pendingMessage.eventId = eventId
            var error = owner.sendError(request.account)
            if (eventId < 0 || error) { owner.finishMessage(error || "Failed"); return }
            owner.pendingMessage.submitted = true
            owner.sendChannel.sendMessage(request.message, eventId)
        })
        return true
    }
    function finishMessage(error) {
        if (!pendingMessage) return
        var completed = pendingMessage
        sendTimer.stop()
        if (error && completed.eventId >= 0)
            groupManager.setEventStatus(completed.eventId, CommHistory.TemporarilyFailedStatus)
        pendingMessage = null
        sendChannel = null
        messageFinished(completed.token, error)
        contentChanged()
    }
}
