"""Navigation1 providers and clients reuse the application's presentation leases."""
import dbus

from .client import SessionClient
from .contract import APP_PATH, NAVIGATION_INTERFACE, method
from .guidance import guidance, validate_guidance
from .model import Fault, state_copy
from .service import Backend, SessionObject, wire_dictionary


def wire_guidance(value):
    value = validate_guidance(value)
    value['updatedMs'] = dbus.UInt64(value['updatedMs'])
    value['remainingSeconds'] = dbus.UInt64(value['remainingSeconds'])
    value['exitNumber'] = dbus.UInt32(value['exitNumber'])
    value['nextDistanceMeters'] = dbus.Double(value['nextDistanceMeters'])
    value['remainingDistanceMeters'] = dbus.Double(value['remainingDistanceMeters'])
    return wire_dictionary(value)


class NavigationSessionObject(SessionObject):
    extra_interfaces = (NAVIGATION_INTERFACE,)

    @method(NAVIGATION_INTERFACE, 'GetGuidance', sender_keyword='sender')
    def GetGuidance(self, sender=None, message=None):
        self.record(sender)
        return dbus.UInt64(self.backend.model.revision), wire_dictionary(self.backend.model.state['navigation'])

    def emit_guidance(self):
        record = self.backend.model.sessions.get(self.path)
        if record is None:
            return
        message = dbus.lowlevel.SignalMessage(self.path, NAVIGATION_INTERFACE, 'GuidanceChanged')
        message.set_destination(record.owner)
        message.append(dbus.UInt64(self.backend.model.revision),
                       wire_dictionary(self.backend.model.state['navigation']), signature='ta{sv}')
        self.backend.bus.send_message(message)


class NavigationBackend(Backend):
    session_type = NavigationSessionObject

    def __init__(self, service, application_id, actions, state=None, bus=None, path=APP_PATH,
                 on_lifecycle=None):
        if 'navigation.stop' not in actions:
            raise ValueError('a navigation provider must implement navigation.stop')
        state = state_copy({} if state is None else state)
        state['navigation'] = wire_guidance(state['navigation'] if 'navigation' in state else guidance())
        super().__init__(service, application_id, state, actions, ('navigation',), bus, path, on_lifecycle)

    def publish(self, state):
        value = state_copy(state)
        if 'navigation' not in value:
            raise Fault('InvalidArgument', 'a navigation provider must retain its guidance model')
        value['navigation'] = wire_guidance(value['navigation'])
        before = self.model.revision
        revision = super().publish(value)
        if revision != before:
            for session in list(self.sessions.values()):
                session.emit_guidance()
        return revision

    def publish_guidance(self, value):
        state = dict(self.model.state)
        state['navigation'] = validate_guidance(value)
        return self.publish(state)


class NavigationClient(SessionClient):
    """Receive guidance through the same revisioned snapshot as other app state."""
    def __init__(self, service, presentation='car', path=APP_PATH, bus=None,
                 on_navigation=None, **callbacks):
        self.guidance = {}
        self.on_navigation = on_navigation or (lambda revision, value: None)
        self._on_state = callbacks.pop('on_state', lambda revision, value: None)
        super().__init__(service, presentation, ('navigation',), path, bus,
                         on_state=self._guidance_state, **callbacks)

    def _guidance_state(self, revision, state):
        if revision == 0:
            self.guidance = {}
        else:
            try:
                self.guidance = validate_guidance(state.get('navigation'))
            except Fault as error:
                self._failed(self._epoch, error)
                return
        self.on_navigation(revision, dict(self.guidance))
        self._on_state(revision, state)
