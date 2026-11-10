"""Application state and caller-owned presentation sessions."""
import copy
import uuid

from .contract import APP_PATH, ERROR_PREFIX


MAX_UINT64 = (1 << 64) - 1


class Fault(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.name = ERROR_PREFIX + code


def state_copy(state):
    if not isinstance(state, dict) or any(not isinstance(key, str) or not key or '\0' in key
                                           for key in state):
        raise Fault('InvalidArgument', 'state must be a dictionary with nonempty string keys')
    return _copy_value(state)


def _copy_value(value):
    if isinstance(value, dict):
        result = {copy.deepcopy(key): _copy_value(item) for key, item in value.items()}
    elif isinstance(value, list):
        result = [_copy_value(item) for item in value]
    elif isinstance(value, tuple):
        result = tuple(_copy_value(item) for item in value)
    else:
        return copy.deepcopy(value)
    if hasattr(value, 'variant_level'):
        keywords = {'variant_level': value.variant_level}
        if hasattr(value, 'signature'):
            keywords['signature'] = value.signature
        return type(value)(result, **keywords)
    return result


class SessionRecord:
    def __init__(self, owner, presentation):
        self.owner = owner
        self.presentation = presentation
        self.active = True
        self.last_request = 0
        self.pending = {}


class ApplicationState:
    def __init__(self, application_id, state, capabilities=(), path=APP_PATH):
        if not isinstance(application_id, str) or not application_id or '\0' in application_id:
            raise Fault('InvalidArgument', 'application identity is required')
        capabilities = tuple(capabilities)
        if any(not isinstance(value, str) or not value or '\0' in value for value in capabilities):
            raise Fault('InvalidArgument', 'capabilities must contain nonempty strings')
        self.application_id = application_id
        self.instance_id = uuid.uuid4().hex
        self.capabilities = tuple(sorted(set(('state', 'actions') + capabilities)))
        self.path = path
        self.state = state_copy(state)
        self.revision = 1
        self.sessions = {}

    def open_session(self, owner, presentation, required):
        if presentation not in ('phone', 'car'):
            raise Fault('NotSupported', 'presentation must be phone or car')
        if not owner or not owner.startswith(':'):
            raise Fault('InvalidArgument', 'session owner must be a unique D-Bus name')
        if not set(required).issubset(self.capabilities):
            raise Fault('NotSupported', 'a required capability is unavailable')
        if len(self.sessions) >= 64:
            raise Fault('LimitExceeded', 'application presentation session limit reached')
        path = self.path + '/sessions/s' + uuid.uuid4().hex
        self.sessions[path] = SessionRecord(owner, presentation)
        return path

    def session(self, path, owner):
        record = self.sessions.get(path)
        if record is None:
            raise Fault('InvalidSession', 'presentation session has closed')
        if record.owner != owner:
            raise Fault('NotOwner', 'presentation session belongs to another caller')
        return record

    def close_session(self, path, owner):
        self.session(path, owner)
        del self.sessions[path]

    def owner_lost(self, owner):
        paths = [path for path, record in self.sessions.items() if record.owner == owner]
        for path in paths:
            del self.sessions[path]
        return paths

    def snapshot(self, path, owner):
        self.session(path, owner)
        return self.revision, state_copy(self.state)

    def check_revision(self, expected):
        if isinstance(expected, bool) or not isinstance(expected, int) or not 0 <= expected <= MAX_UINT64:
            raise Fault('InvalidArgument', 'expected revision must be an unsigned 64-bit integer')
        if expected and expected != self.revision:
            raise Fault('StaleRevision', 'application state has changed')

    def begin_request(self, path, owner, request_id, expected):
        record = self.session(path, owner)
        if isinstance(request_id, bool) or not isinstance(request_id, int) or not 1 <= request_id <= MAX_UINT64:
            raise Fault('InvalidArgument', 'request ID must be a positive unsigned 64-bit integer')
        if request_id <= record.last_request:
            raise Fault('DuplicateRequest', 'request IDs must increase within a presentation session')
        self.check_revision(expected)
        if len(record.pending) >= 64:
            raise Fault('LimitExceeded', 'presentation request limit reached')
        record.last_request = request_id
        record.pending[request_id] = expected

    def publish(self, state):
        value = state_copy(state)
        if value == self.state:
            return False
        if self.revision == MAX_UINT64:
            raise Fault('LimitExceeded', 'application revision limit reached')
        self.state = value
        self.revision += 1
        return True
