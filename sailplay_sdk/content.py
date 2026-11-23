"""Content1 providers reuse the application's session and asynchronous actions."""
import dbus

from .client import SessionClient
from .content_model import content_page, merge_content, split_content, validate_content, validate_query
from .contract import APP_PATH, CONTENT_INTERFACE, method
from .model import Fault, state_copy
from .service import Backend, SessionObject, wire_dictionary


def wire_presentation(value):
    """The hints of a page as `a{sv}`; an empty dictionary when it has none."""
    _, presentation = split_content(value)
    if 'items' in presentation:
        presentation['items'] = dbus.Dictionary(
            {identity: wire_dictionary(hints) for identity, hints in presentation['items'].items()}, signature='sv')
    return wire_dictionary(presentation) if presentation else {}


def content_result(value):
    """A query result: the page, and its presentation when it has one."""
    result = {'content': wire_content(value)}
    presentation = wire_presentation(value)
    if presentation:
        result['presentation'] = presentation
    return result


def _state_with_presentation(state, default=None):
    """Publish the root page's hints beside it, under `contentPresentation`."""
    value = state_copy(state)
    root = value.get('content', default)
    value['content'] = wire_root(root)
    presentation = wire_presentation(root)
    if presentation:
        value['contentPresentation'] = presentation
    else:
        value.pop('contentPresentation', None)
    return value


def wire_content(value):
    value, _ = split_content(value)
    value['offset'] = dbus.UInt32(value['offset'])
    value['version'] = dbus.UInt64(value['version'])
    for key in ('items', 'actions'):
        for item in value[key]:
            item['parameters'] = wire_dictionary(item['parameters'])
        value[key] = dbus.Array([wire_dictionary(item) for item in value[key]], signature='a{sv}')
    return wire_dictionary(value)


def wire_root(value):
    value = wire_content(value)
    if value['id'] != 'root' or value['offset'] != 0:
        raise Fault('InvalidArgument', 'application content must retain its root page')
    return value


class ContentSessionObject(SessionObject):
    extra_interfaces = (CONTENT_INTERFACE,)

    @method(CONTENT_INTERFACE, 'GetContent', sender_keyword='sender')
    def GetContent(self, sender=None, message=None):
        self.record(sender)
        return dbus.UInt64(self.backend.model.revision), self.backend.model.state['content']

    def emit_content(self):
        record = self.backend.model.sessions.get(self.path)
        if record is None:
            return
        message = dbus.lowlevel.SignalMessage(self.path, CONTENT_INTERFACE, 'ContentChanged')
        message.set_destination(record.owner)
        message.append(dbus.UInt64(self.backend.model.revision), self.backend.model.state['content'], signature='ta{sv}')
        self.backend.bus.send_message(message)


class ContentBackend(Backend):
    session_type = ContentSessionObject

    def __init__(self, service, application_id, actions, state=None, bus=None, path=APP_PATH,
                 on_lifecycle=None):
        if not {'content.browse', 'content.search'}.issubset(actions):
            raise ValueError('content providers must implement browse and search')
        actions = dict(actions)
        for name in ('content.browse', 'content.search'):
            handler = actions[name]
            actions[name] = lambda parameters, invocation, handler=handler, name=name: handler(
                validate_query(parameters, search=name == 'content.search'), invocation)
        state = _state_with_presentation({} if state is None else state, content_page())
        super().__init__(service, application_id, state, actions, ('content',), bus, path, on_lifecycle)

    def publish(self, state):
        value = _state_with_presentation(state)
        before = self.model.revision
        revision = super().publish(value)
        if revision != before:
            for session in list(self.sessions.values()):
                session.emit_content()
        return revision


class ContentClient(SessionClient):
    def __init__(self, service, presentation='car', path=APP_PATH, bus=None, on_content=None, **callbacks):
        self.content = {}
        self.on_content = on_content or (lambda revision, value: None)
        self._on_state = callbacks.pop('on_state', lambda revision, value: None)
        super().__init__(service, presentation, ('content',), path, bus,
                         on_state=self._content_state, **callbacks)

    def _content_state(self, revision, state):
        try:
            self.content = {} if not revision else merge_content(
                validate_content(state.get('content')), state.get('contentPresentation'))
        except Fault as error:
            self._failed(self._epoch, error)
            return
        self.on_content(revision, state_copy(self.content))
        self._on_state(revision, state)
