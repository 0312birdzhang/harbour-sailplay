"""Exercise the SDK on a private bus through its public provider/client entry points."""
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
if not (ROOT / 'sailplay_sdk').is_dir():
    ROOT = pathlib.Path('/opt/sailplay')
EXAMPLES = ROOT / 'sdk/examples'
if not EXAMPLES.is_dir():
    EXAMPLES = pathlib.Path('/usr/share/sailplay-sdk/examples')
sys.path.insert(0, str(ROOT))

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from sailplay_sdk.client import SessionClient
from sailplay_sdk.contract import APP_INTERFACE, APP_PATH, ERROR_PREFIX, SESSION_INTERFACE, interface_xml
from sailplay_sdk.service import Backend


def wait(predicate, seconds=5):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, 'SDK event deadline exceeded'
        while context.pending():
            context.iteration(False)
        time.sleep(.005)


def expect_error(function, name):
    try:
        function()
    except dbus.exceptions.DBusException as error:
        assert error.get_dbus_name() == name, error
    else:
        raise AssertionError('Expected D-Bus error ' + name)


def start(value=0):
    process = subprocess.Popen([sys.executable, str(EXAMPLES / 'counter-service.py'),
                                '--value', str(value)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True)
    line = process.stdout.readline()
    assert line, process.stderr.read()
    return process


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        output, error = process.communicate(timeout=5)
        assert process.returncode == 0, (output, error)


def check_xml(bus, service, path, interface):
    proxy = bus.get_object(service, path, introspect=False)
    text = dbus.Interface(proxy, 'org.freedesktop.DBus.Introspectable').Introspect()
    actual = ET.fromstring(str(text)).find("interface[@name='{}']".format(interface))
    expected = ET.fromstring(interface_xml(interface)).find('interface')
    assert ET.tostring(actual) == ET.tostring(expected), text


def session_gone(bus, service, path):
    proxy = bus.get_object(service, path, introspect=False)
    try:
        text = proxy.Introspect(dbus_interface='org.freedesktop.DBus.Introspectable')
    except dbus.exceptions.DBusException as error:
        assert error.get_dbus_name() in ('org.freedesktop.DBus.Error.UnknownObject',
                                         'org.freedesktop.DBus.Error.UnknownMethod'), error
        return True
    return SESSION_INTERFACE not in text


def main():
    DBusGMainLoop(set_as_default=True)
    service = 'org.example.SailplayCounter'
    activated_service = 'org.example.SailplayActivatedCounter'
    backend = None
    clients = []
    spy = dbus.SessionBus(private=True)
    spy.set_exit_on_disconnect(False)
    spy_events = []
    spy_match = spy.add_signal_receiver(lambda *arguments: spy_events.append(arguments),
                                        signal_name='StateChanged', dbus_interface=SESSION_INTERFACE)
    try:
        activated_errors = []
        activated = SessionClient(activated_service, on_error=lambda *args: activated_errors.append(args))
        clients.append(activated)
        activated.open()
        wait(lambda: activated.ready or bool(activated_errors))
        assert activated.ready and not activated_errors, activated_errors
        assert activated.state['value'] == 0
        activated_name = activated._client_name
        assert spy.get_name_owner(activated_name) == activated.bus.get_unique_name()
        activated.close()
        assert not spy.name_has_owner(activated_name)
        backend = start()
        existing = 'org.example.ExistingApp'
        spy.request_name(existing, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
        adapter = Backend(existing, 'existing-app', {}, {}, bus=spy)
        adapter.close()
        assert spy.get_name_owner(existing) == spy.get_unique_name()
        completions, errors = [], []
        car = SessionClient(service, on_request=lambda *args: completions.append(('car', args)),
                            on_error=lambda *args: errors.append(args))
        phone = SessionClient(service, 'phone', on_request=lambda *args: completions.append(('phone', args)),
                              on_error=lambda *args: errors.append(args))
        clients += [car, phone]
        car.open()
        phone.open()
        wait(lambda: car.ready and phone.ready)
        car_name, phone_name = car._client_name, phone._client_name
        assert car_name != phone_name
        assert spy.get_name_owner(car_name) == car.bus.get_unique_name()
        assert spy.get_name_owner(phone_name) == phone.bus.get_unique_name()
        assert not errors and car.revision == phone.revision == 1
        assert car.state['value'] == phone.state['value'] == 0
        check_xml(car.bus, service, APP_PATH, APP_INTERFACE)
        check_xml(car.bus, service, car.session_path, SESSION_INTERFACE)
        attacker = dbus.Interface(spy.get_object(service, car.session_path, introspect=False), SESSION_INTERFACE)
        for function in (attacker.GetSnapshot, lambda: attacker.SetActive(False), attacker.Close,
                         lambda: attacker.Invoke(dbus.UInt64(1), 'increment', dbus.Dictionary({}, signature='sv'), dbus.UInt64(0))):
            expect_error(function, ERROR_PREFIX + 'NotOwner')

        own = dbus.Interface(car.bus.get_object(service, car.session_path, introspect=False), SESSION_INTERFACE)
        expect_error(lambda: own.GetSnapshot('extra'), 'org.freedesktop.DBus.Error.InvalidArgs')
        expect_error(lambda: own.Invoke('1', 'increment', dbus.Dictionary({}, signature='sv'), dbus.UInt64(0)),
                     'org.freedesktop.DBus.Error.InvalidArgs')
        car.invoke('increment', {'amount': 3}, car.revision)
        wait(lambda: len(completions) == 1 and phone.state['value'] == car.state['value'] == 3)
        assert completions[0][1][3] == ''
        assert car.revision == phone.revision == 2
        expect_error(lambda: own.Invoke(dbus.UInt64(1), 'increment', dbus.Dictionary({}, signature='sv'), dbus.UInt64(0)),
                     ERROR_PREFIX + 'DuplicateRequest')
        expect_error(lambda: own.Invoke(dbus.UInt64(2), 'missing', dbus.Dictionary({}, signature='sv'), dbus.UInt64(0)),
                     ERROR_PREFIX + 'NotSupported')

        car.set_active(False)
        properties = dbus.Interface(car.bus.get_object(service, car.session_path, introspect=False),
                                    'org.freedesktop.DBus.Properties')
        wait(lambda: not properties.Get(SESSION_INTERFACE, 'Active'))
        revision = car.revision
        car.invoke('increment', {'delayMs': 40}, revision)
        phone.invoke('increment', {'delayMs': 40}, revision)
        wait(lambda: len(completions) == 3)
        outcomes = [args[3] for _, args in completions[1:]]
        assert outcomes.count('') == 1 and outcomes.count(ERROR_PREFIX + 'StaleRevision') == 1, outcomes
        wait(lambda: car.state['value'] == phone.state['value'] == 4)
        car.invoke('increment', {'amount': True})
        wait(lambda: len(completions) == 4)
        assert completions[-1][1][3] == ERROR_PREFIX + 'InvalidArgument'
        assert car.state['value'] == 4 and not spy_events
        car.invoke('increment', {'amount': 1.0, 'delayMs': 0.0})
        wait(lambda: len(completions) == 5 and car.state['value'] == 5)
        assert completions[-1][1][3] == ''
        transient = SessionClient(service, 'phone')
        clients.append(transient)
        transient.open()
        wait(lambda: transient.ready)
        pending = dbus.Interface(transient.bus.get_object(service, transient.session_path, introspect=False),
                                  SESSION_INTERFACE)
        pending.Invoke(dbus.UInt64(1), 'increment',
                       dbus.Dictionary({'amount': 4, 'delayMs': 60}, signature='sv'), dbus.UInt64(0))
        transient.close()
        wait(lambda: car.state['value'] == phone.state['value'] == 9)

        unavailable = []
        bad = SessionClient(service, capabilities=('missing',), on_error=lambda *args: unavailable.append(args))
        clients.append(bad)
        bad.open()
        wait(lambda: bool(unavailable))
        assert unavailable[0][0] == ERROR_PREFIX + 'NotSupported'
        bad.close()
        phone_path = phone.session_path
        phone.close()
        assert not spy.name_has_owner(phone_name) and spy.name_has_owner(car_name)
        wait(lambda: session_gone(spy, service, phone_path))
        assert car.ready and car.state['value'] == 9

        instance = car.instance_id
        car.invoke('increment', {'delayMs': 2000})
        stop(backend)
        backend = None
        wait(lambda: not car.ready and len(completions) == 6)
        assert not car.state and car.revision == 0
        assert completions[-1][1][3] == ERROR_PREFIX + 'Disconnected'
        backend = start(30)
        wait(lambda: car.ready and car.instance_id != instance)
        assert car._client_name == car_name
        assert spy.get_name_owner(car_name) == car.bus.get_unique_name()
        assert car.revision == 1 and car.state['value'] == 30
        car.invoke('increment', {'amount': 2}, car.revision)
        wait(lambda: len(completions) == 7 and car.state['value'] == 32)
        assert completions[-1][1][0] == 1 and completions[-1][1][3] == ''
        assert not errors
        print('SDK_BUS_CONTRACT_PASS ' + json.dumps({'initial_revision': 1, 'restarted_revision': 1,
              'final_value': int(car.state['value']), 'request_completions': len(completions),
              'caller_isolation': True, 'unicast_state': True, 'canonical_introspection': True,
              'stale_revision_rejected': True, 'backend_reconnected': True, 'background_activation': True,
              'accepted_work_survived_view_close': True, 'named_client_lifecycle': True}), flush=True)
    finally:
        for client in clients:
            client.close()
        try:
            owner = spy.get_name_owner(activated_service)
        except dbus.exceptions.DBusException as error:
            assert error.get_dbus_name() == 'org.freedesktop.DBus.Error.NameHasNoOwner', error
        else:
            daemon = dbus.Interface(spy.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'),
                                    'org.freedesktop.DBus')
            pid = int(daemon.GetConnectionUnixProcessID(owner))
            command = pathlib.Path('/proc', str(pid), 'cmdline').read_bytes()
            assert activated_service.encode() in command and b'counter-service.py' in command, command
            assert spy.get_name_owner(activated_service) == owner
            os.kill(pid, signal.SIGTERM)
            wait(lambda: not spy.name_has_owner(activated_service))
        spy_match.remove()
        spy.close()
        stop(backend)


if __name__ == '__main__':
    main()
