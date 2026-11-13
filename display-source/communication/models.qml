import QtQml 2.2
import org.nemomobile.contacts 1.0
import org.nemomobile.commhistory 1.0
import org.nemomobile.voicecall 1.0
import Sailfish.Messages 1.0

QtObject {
    id: models
    signal contentChanged()
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
}
