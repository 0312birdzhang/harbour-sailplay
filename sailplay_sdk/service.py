"""Export SDK interfaces on an application's session-bus identity."""
import threading
import logging
import xml.etree.ElementTree as ET

import dbus
import dbus.service
from gi.repository import GLib

from .contract import (API_VERSION, APP_INTERFACE, APP_PATH, SESSION_INTERFACE,
                       interface_xml, method, signatures)
from .model import ApplicationState, Fault, state_copy


PROPERTIES = 'org.freedesktop.DBus.Properties'


def wire_dictionary(value):
    result = dbus.Dictionary(state_copy(value), signature='sv')
    probe = dbus.lowlevel.SignalMessage(APP_PATH, SESSION_INTERFACE, 'StateChanged')
    probe.append(result, signature='a{sv}')
    return result


def raise_dbus(fault):
    raise dbus.exceptions.DBusException(str(fault), name=fault.name)


class Invocation:
    """An accepted action can finish once, including from a worker thread."""
    def __init__(self, backend, path, request_id, record):
        self.backend = backend
        self.path = path
        self.request_id = request_id
        self.record = record
        self._lock = threading.Lock()
        self._finished = False

    def complete(self, result=None, state=None):
        return self._finish({} if result is None else result, state, None)

    def fail(self, code, message):
        return self._finish({}, None, Fault(code, message))

    def _finish(self, result, state, fault):
        with self._lock:
            if self._finished:
                return False
            self._finished = True
        try:
            result = state_copy(result)
            state = state_copy(state) if state is not None else None
        except Fault as error:
            result, state, fault = {}, None, error
        except Exception as error:
            result, state, fault = {}, None, Fault('InvalidArgument', str(error))
        GLib.idle_add(self.backend._finish, self, result, state, fault)
        return True


class ExportedObject(dbus.service.Object):
    extra_interfaces = ()

    @dbus.service.method(PROPERTIES, in_signature='s', out_signature='a{sv}', sender_keyword='sender')
    def GetAll(self, interface, sender=None):
        if interface not in (self.interface,) + self.extra_interfaces:
            raise dbus.exceptions.DBusException('unknown interface', name='org.freedesktop.DBus.Error.UnknownInterface')
        values = self.properties(sender)
        return values if interface == self.interface else {}

    @dbus.service.method(PROPERTIES, in_signature='ss', out_signature='v', sender_keyword='sender')
    def Get(self, interface, name, sender=None):
        values = self.GetAll(interface, sender)
        if name not in values:
            raise dbus.exceptions.DBusException('unknown property', name='org.freedesktop.DBus.Error.UnknownProperty')
        return values[name]

    @dbus.service.method(PROPERTIES, in_signature='ssv', out_signature='')
    def Set(self, interface, name, value):
        raise dbus.exceptions.DBusException('SDK properties are read-only',
                                            name='org.freedesktop.DBus.Error.PropertyReadOnly')

    @dbus.service.method('org.freedesktop.DBus.Introspectable', in_signature='', out_signature='s',
                         path_keyword='object_path', connection_keyword='connection')
    def Introspect(self, object_path=None, connection=None):
        root = ET.fromstring(super().Introspect(object_path, connection))
        for interface in (self.interface,) + self.extra_interfaces:
            for element in root.findall('interface'):
                if element.get('name') == interface:
                    root.remove(element)
            root.insert(0, ET.fromstring(interface_xml(interface)).find('interface'))
        properties = root.find("interface[@name='org.freedesktop.DBus.Properties']")
        properties.append(ET.fromstring(
            '<signal name="PropertiesChanged">'
            '<arg name="interface" type="s"/>'
            '<arg name="changed" type="a{sv}"/>'
            '<arg name="invalidated" type="as"/>'
            '</signal>'))
        return ET.tostring(root, encoding='unicode')


class AppObject(ExportedObject):
    interface = APP_INTERFACE

    def __init__(self, backend):
        self.backend = backend
        super().__init__(backend.bus, backend.model.path)

    def properties(self, sender):
        model = self.backend.model
        return {'ApiVersion': dbus.UInt32(API_VERSION), 'ApplicationId': model.application_id,
                'InstanceId': model.instance_id, 'Capabilities': dbus.Array(model.capabilities, signature='s')}

    @method(APP_INTERFACE, 'OpenSession', sender_keyword='sender')
    def OpenSession(self, presentation, requiredCapabilities, sender=None, message=None):
        try:
            path = self.backend.model.open_session(sender, str(presentation), requiredCapabilities)
            try:
                self.backend.sessions[path] = self.backend.session_type(self.backend, path)
            except Exception:
                self.backend.model.close_session(path, sender)
                raise
            self.backend._lifecycle_changed()
            return dbus.ObjectPath(path)
        except Fault as fault:
            raise_dbus(fault)


class SessionObject(ExportedObject):
    interface = SESSION_INTERFACE

    def __init__(self, backend, path):
        self.backend, self.path = backend, path
        super().__init__(backend.bus, path)

    def record(self, sender):
        try:
            return self.backend.model.session(self.path, sender)
        except Fault as fault:
            raise_dbus(fault)

    def properties(self, sender):
        record = self.record(sender)
        return {'Presentation': record.presentation, 'Active': dbus.Boolean(record.active)}

    @method(SESSION_INTERFACE, 'GetSnapshot', sender_keyword='sender')
    def GetSnapshot(self, sender=None, message=None):
        self.record(sender)
        return dbus.UInt64(self.backend.model.revision), wire_dictionary(self.backend.model.state)

    @method(SESSION_INTERFACE, 'SetActive', sender_keyword='sender')
    def SetActive(self, active, sender=None, message=None):
        record = self.record(sender)
        if record.active != bool(active):
            record.active = bool(active)
            message = dbus.lowlevel.SignalMessage(self.path, PROPERTIES, 'PropertiesChanged')
            message.set_destination(record.owner)
            message.append(SESSION_INTERFACE, {'Active': dbus.Boolean(record.active)},
                           dbus.Array([], signature='s'), signature='sa{sv}as')
            self.backend.bus.send_message(message)
            self.backend._lifecycle_changed()

    @method(SESSION_INTERFACE, 'Invoke', sender_keyword='sender')
    def Invoke(self, requestId, action, parameters, expectedRevision, sender=None, message=None):
        record = self.record(sender)
        if action not in self.backend.actions:
            raise_dbus(Fault('NotSupported', 'application action is unavailable'))
        try:
            parameters = state_copy(parameters)
            self.backend.model.begin_request(self.path, sender, int(requestId), int(expectedRevision))
        except Fault as fault:
            raise_dbus(fault)
        invocation = Invocation(self.backend, self.path, int(requestId), record)
        self.backend._invocations.add(invocation)
        GLib.idle_add(self.backend._run, invocation, str(action), parameters)
        self.backend._lifecycle_changed()

    @method(SESSION_INTERFACE, 'Close', sender_keyword='sender')
    def Close(self, sender=None, message=None):
        self.record(sender)
        self.backend.model.close_session(self.path, sender)
        self.backend.sessions.pop(self.path).remove_from_connection()
        self.backend._lifecycle_changed()

    def emit(self, member, *arguments):
        record = self.backend.model.sessions.get(self.path)
        if record is None:
            return
        message = dbus.lowlevel.SignalMessage(self.path, SESSION_INTERFACE, member)
        message.set_destination(record.owner)
        message.append(*arguments, signature=signatures(SESSION_INTERFACE, member, 'signal')[1])
        self.backend.bus.send_message(message)


class Backend:
    """Own one application state while each caller owns its presentation session."""
    session_type = SessionObject

    def __init__(self, service, application_id, state, actions, capabilities=(), bus=None, path=APP_PATH,
                 on_lifecycle=None):
        if on_lifecycle is not None and not callable(on_lifecycle):
            raise ValueError('application lifecycle handler must be callable')
        dbus.validate_bus_name(service)
        dbus.validate_object_path(path)
        if service.startswith(':'):
            raise ValueError('backend service must be an application well-known name')
        self.model = ApplicationState(application_id, wire_dictionary(state), capabilities, path)
        self.actions = dict(actions)
        if any(not isinstance(name, str) or not name or not callable(handler)
               for name, handler in self.actions.items()):
            raise ValueError('application actions require names and callable handlers')
        self.bus = bus if bus is not None else dbus.SessionBus(private=True)
        self._own_bus = bus is None
        if self._own_bus:
            self.bus.set_exit_on_disconnect(False)
        self.service = service
        self.sessions = {}
        self._invocations = set()
        self.on_lifecycle = on_lifecycle
        self.app = None
        self._watch = None
        self._owns_name = False
        self._closed = False
        self._thread = threading.get_ident()
        try:
            result = self.bus.request_name(service, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
            if result not in (dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER, dbus.bus.REQUEST_NAME_REPLY_ALREADY_OWNER):
                raise RuntimeError('application D-Bus name already has an owner')
            self._owns_name = result == dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER
            self._watch = self.bus.add_signal_receiver(self._owner_changed, signal_name='NameOwnerChanged',
                dbus_interface='org.freedesktop.DBus', bus_name='org.freedesktop.DBus')
            self.app = AppObject(self)
        except Exception:
            self.close()
            raise

    def _owner_changed(self, name, old, new):
        if old and not new:
            paths = self.model.owner_lost(str(name))
            for path in paths:
                self.sessions.pop(path).remove_from_connection()
            if paths:
                self._lifecycle_changed()

    @property
    def session_count(self):
        return len(self.sessions)

    @property
    def active_session_count(self):
        return sum(record.active for record in self.model.sessions.values())

    @property
    def pending_count(self):
        return len(self._invocations)

    def _lifecycle_changed(self):
        if self.on_lifecycle is not None and not self._closed:
            try:
                self.on_lifecycle(self)
            except Exception:
                logging.exception('application lifecycle callback failed')

    def publish(self, state):
        if self._closed:
            raise RuntimeError('application backend has closed')
        if threading.get_ident() != self._thread:
            raise RuntimeError('publish state on the backend GLib thread')
        value = wire_dictionary(state)
        if self.model.publish(value):
            for session in list(self.sessions.values()):
                session.emit('StateChanged', dbus.UInt64(self.model.revision), value)
        return self.model.revision

    def _run(self, invocation, action, parameters):
        record = invocation.record
        if self._closed or invocation.request_id not in record.pending:
            return False
        try:
            self.model.check_revision(record.pending[invocation.request_id])
            self.actions[action](parameters, invocation)
        except Fault as fault:
            invocation.fail(fault.name.rsplit('.', 1)[1], str(fault))
        except Exception as error:
            invocation.fail('Failed', str(error))
        return False

    def _finish(self, invocation, result, state, fault):
        record = invocation.record
        if self._closed or invocation.request_id not in record.pending:
            return False
        if fault is None:
            try:
                result = wire_dictionary(result)
                if state is not None:
                    self.model.check_revision(record.pending[invocation.request_id])
                    self.publish(state)
            except Fault as error:
                fault = error
            except Exception as error:
                fault = Fault('InvalidArgument', str(error))
        del record.pending[invocation.request_id]
        self._invocations.discard(invocation)
        session = self.sessions.get(invocation.path)
        if session is not None:
            session.emit('RequestFinished', dbus.UInt64(invocation.request_id),
                dbus.UInt64(self.model.revision), result if fault is None else wire_dictionary({}),
                fault.name if fault is not None else '', str(fault) if fault is not None else '')
        self._lifecycle_changed()
        return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._watch is not None:
            self._watch.remove()
        for session in self.sessions.values():
            session.remove_from_connection()
        self.sessions.clear()
        self.model.sessions.clear()
        self._invocations.clear()
        if self.app is not None:
            self.app.remove_from_connection()
        if self._owns_name and self.bus.get_is_connected():
            self.bus.release_name(self.service)
        if self._own_bus:
            self.bus.close()
