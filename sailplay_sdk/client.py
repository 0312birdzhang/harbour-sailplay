"""Asynchronous Python binding for an application's SDK presentation session."""
import uuid

import dbus
from gi.repository import GLib

from .contract import API_VERSION, APP_INTERFACE, APP_PATH, ERROR_PREFIX, SESSION_INTERFACE, signatures
from .model import Fault, MAX_UINT64


class SessionClient:
    def __init__(self, service, presentation='car', capabilities=(), path=APP_PATH, bus=None,
                 on_ready=None, on_state=None, on_request=None, on_error=None):
        dbus.validate_bus_name(service)
        dbus.validate_object_path(path)
        if service.startswith(':') or presentation not in ('phone', 'car'):
            raise ValueError('an application service and phone/car presentation are required')
        self.required_capabilities = tuple(capabilities)
        self.bus = bus if bus is not None else dbus.SessionBus(private=True)
        self._own_bus = bus is None
        if self._own_bus:
            self.bus.set_exit_on_disconnect(False)
        self.service, self.path, self.presentation = service, path, presentation
        self.on_ready = on_ready or (lambda ready: None)
        self.on_state = on_state or (lambda revision, state: None)
        self.on_request = on_request or (lambda request, revision, result, name, message: None)
        self.on_error = on_error or (lambda name, message: None)
        self.ready = False
        self.revision = 0
        self.state = {}
        self.application_id = ''
        self.instance_id = ''
        self.capabilities = ()
        self.session_path = ''
        self._owner = ''
        self._epoch = 0
        self._sequence = 0
        self._pending = set()
        self._matches = []
        self._wanted = False
        self._closed = False
        self._watch = None
        self._client_name = ''
        try:
            name = 'org.sailplay.Client.c' + uuid.uuid4().hex
            if self.bus.request_name(name, dbus.bus.NAME_FLAG_DO_NOT_QUEUE) != dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER:
                raise Fault('Failed', 'presentation client name is unavailable')
            self._client_name = name
            self._watch = self.bus.add_signal_receiver(self._owner_changed, signal_name='NameOwnerChanged',
                dbus_interface='org.freedesktop.DBus', bus_name='org.freedesktop.DBus', arg0=service)
            self._daemon = dbus.Interface(self.bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                                            introspect=False), 'org.freedesktop.DBus')
        except Exception:
            if self._watch is not None:
                self._watch.remove()
            self._release_client_name()
            if self._own_bus:
                self.bus.close()
            raise

    def open(self):
        if self._closed:
            raise RuntimeError('presentation client has closed')
        self._wanted = True
        self._epoch += 1
        epoch = self._epoch
        self._reset()
        if not self._alive(epoch):
            return
        self._daemon.GetNameOwner(self.service,
            reply_handler=lambda owner: self._connect(epoch, str(owner)),
            error_handler=lambda error: self._missing(epoch, error), timeout=5)

    def _missing(self, epoch, error):
        if not self._alive(epoch):
            return
        if error.get_dbus_name() != 'org.freedesktop.DBus.Error.NameHasNoOwner':
            self._failed(epoch, error)
            return
        self._daemon.StartServiceByName(self.service, dbus.UInt32(0),
            reply_handler=lambda result: self._started(epoch),
            error_handler=lambda error: self._failed(epoch, error), timeout=5)

    def _alive(self, epoch):
        return not self._closed and self._wanted and epoch == self._epoch

    def _started(self, epoch):
        if self._alive(epoch):
            self._daemon.GetNameOwner(self.service,
                reply_handler=lambda owner: self._connect(epoch, str(owner)),
                error_handler=lambda error: self._failed(epoch, error), timeout=5)

    def _connect(self, epoch, owner):
        if not self._alive(epoch):
            return
        self._owner = owner
        self.bus.call_async(owner, self.path, 'org.freedesktop.DBus.Properties', 'GetAll', 's',
            (APP_INTERFACE,), reply_handler=lambda values: self._info(epoch, owner, values),
            error_handler=lambda error: self._failed(epoch, error), timeout=5)

    def _info(self, epoch, owner, values):
        if not self._alive(epoch):
            return
        try:
            if int(values['ApiVersion']) != API_VERSION:
                raise Fault('NotSupported', 'application SDK version is unavailable')
            self.application_id = str(values['ApplicationId'])
            self.instance_id = str(values['InstanceId'])
            self.capabilities = tuple(str(value) for value in values['Capabilities'])
            if not self.application_id or not self.instance_id:
                raise Fault('InvalidArgument', 'application identity is incomplete')
            if not set(self.required_capabilities).issubset(self.capabilities):
                raise Fault('NotSupported', 'a required capability is unavailable')
            self._call(APP_INTERFACE, 'OpenSession', (self.presentation, self.required_capabilities),
                lambda path: self._opened(epoch, owner, str(path)),
                lambda error: self._failed(epoch, error), path=self.path)
        except Exception as error:
            self._failed(epoch, error)

    def _opened(self, epoch, owner, path):
        if not self._alive(epoch):
            self._retire(owner, path)
            return
        self.session_path = path
        try:
            self._matches.append(self.bus.add_signal_receiver(
                lambda revision, state: self._state(epoch, revision, state),
                signal_name='StateChanged', dbus_interface=SESSION_INTERFACE, bus_name=owner, path=path))
            self._matches.append(self.bus.add_signal_receiver(
                lambda *arguments: self._finished(epoch, *arguments),
                signal_name='RequestFinished', dbus_interface=SESSION_INTERFACE, bus_name=owner, path=path))
            self._call(SESSION_INTERFACE, 'GetSnapshot', (),
                lambda revision, state: self._snapshot(epoch, revision, state),
                lambda error: self._failed(epoch, error))
        except Exception as error:
            self._failed(epoch, error)

    def _snapshot(self, epoch, revision, state):
        if not self._alive(epoch):
            return
        self._state(epoch, revision, state)
        if self._alive(epoch):
            self.ready = True
            self.on_ready(True)

    def _state(self, epoch, revision, state):
        if self._alive(epoch) and int(revision) > self.revision:
            self.revision, self.state = int(revision), dict(state)
            self.on_state(self.revision, self.state)

    def _call(self, interface, member, arguments, reply, error, path=None, owner=None):
        return self.bus.call_async(owner or self._owner, path or self.session_path, interface, member,
            signatures(interface, member)[0], arguments, reply_handler=reply, error_handler=error, timeout=5)

    def invoke(self, action, parameters=None, expected_revision=0):
        if not self.ready:
            raise Fault('Disconnected', 'presentation session is not ready')
        if self._sequence == MAX_UINT64:
            raise Fault('LimitExceeded', 'presentation request ID limit reached')
        self._sequence += 1
        request_id, epoch = self._sequence, self._epoch
        self._pending.add(request_id)
        try:
            self._call(SESSION_INTERFACE, 'Invoke',
                (request_id, action, {} if parameters is None else parameters, expected_revision),
                lambda: None, lambda error: self._invoke_failed(epoch, request_id, error))
        except Exception as error:
            GLib.idle_add(self._invoke_failed, epoch, request_id, error)
        return request_id

    def set_active(self, active):
        if not self.ready:
            raise Fault('Disconnected', 'presentation session is not ready')
        epoch = self._epoch
        self._call(SESSION_INTERFACE, 'SetActive', (bool(active),), lambda: None,
                   lambda error: self._failed(epoch, error))

    def _finished(self, epoch, request_id, revision, result, name, message):
        request_id = int(request_id)
        if self._alive(epoch) and request_id in self._pending:
            self._pending.remove(request_id)
            self.on_request(request_id, int(revision), dict(result), str(name), str(message))

    def _invoke_failed(self, epoch, request_id, error):
        if self._alive(epoch) and request_id in self._pending:
            name = getattr(error, 'get_dbus_name', lambda: getattr(error, 'name', ERROR_PREFIX + 'InvalidArgument'))()
            self._finished(epoch, request_id, self.revision, {}, name, str(error))
        return False

    def _failed(self, epoch, error):
        if self._alive(epoch):
            self._epoch += 1
            self._reset()
            name = getattr(error, 'get_dbus_name', lambda: getattr(error, 'name', ERROR_PREFIX + 'Failed'))()
            self.on_error(name, str(error))

    def _retire(self, owner, path):
        try:
            self._call(SESSION_INTERFACE, 'Close', (), lambda: None, lambda error: None, path=path, owner=owner)
        except dbus.exceptions.DBusException:
            pass

    def _reset(self):
        if self._owner and self.session_path:
            self._retire(self._owner, self.session_path)
        for match in self._matches:
            match.remove()
        self._matches = []
        was_ready, had_state = self.ready, self.revision > 0
        requests = sorted(self._pending)
        self._pending.clear()
        self._owner, self.session_path = '', ''
        self._sequence, self.revision = 0, 0
        self.application_id, self.instance_id, self.capabilities = '', '', ()
        self.state = {}
        self.ready = False
        if was_ready:
            self.on_ready(False)
        if had_state:
            self.on_state(0, {})
        for request_id in requests:
            self.on_request(request_id, 0, {}, ERROR_PREFIX + 'Disconnected', 'application session ended')

    def _owner_changed(self, name, old, new):
        if not self._wanted or self._closed or str(new) == self._owner:
            return
        self._epoch += 1
        epoch = self._epoch
        self._reset()
        if new:
            self._connect(epoch, str(new))

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._wanted = False
        self._epoch += 1
        try:
            self._reset()
        finally:
            self._watch.remove()
            self._release_client_name()
            if self._own_bus:
                self.bus.close()

    def _release_client_name(self):
        name, self._client_name = self._client_name, ''
        if name:
            try:
                self.bus.release_name(name)
            except dbus.exceptions.DBusException:
                pass
