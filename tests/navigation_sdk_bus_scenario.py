"""Exercise Navigation1 and presentation lifecycle through actual D-Bus calls."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
if not (ROOT / 'sailplay_sdk').is_dir():
    ROOT = pathlib.Path('/opt/sailplay')
sys.path.insert(0, str(ROOT))
EXAMPLES = ROOT / 'sdk/examples'
if not EXAMPLES.is_dir():
    EXAMPLES = pathlib.Path('/usr/share/sailplay-sdk/examples')

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from sailplay_sdk.contract import NAVIGATION_INTERFACE, SESSION_INTERFACE, interface_xml
from sailplay_sdk.guidance import guidance
from sailplay_sdk.navigation import NavigationClient


def wait(predicate, seconds=5):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, 'Navigation SDK event deadline exceeded'
        while context.pending():
            context.iteration(False)
        time.sleep(.005)


def call(bus, owner, path, interface, member, signature='', arguments=(), error=None):
    results, errors = [], []
    bus.call_async(owner, path, interface, member, signature, arguments,
                   reply_handler=lambda *values: results.append(values), error_handler=errors.append, timeout=3)
    wait(lambda: bool(results or errors))
    if error:
        assert errors and errors[0].get_dbus_name() == error, errors
        return
    assert not errors, errors
    return results[0]


def main():
    DBusGMainLoop(set_as_default=True)
    specification = importlib.util.spec_from_file_location('fake_navigation', EXAMPLES / 'navigation-service.py')
    example = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(example)
    loop = GLib.MainLoop()
    providers, clients = [], []
    reference = None
    spy = dbus.SessionBus(private=True)
    spy.set_exit_on_disconnect(False)
    leaked = []
    match = spy.add_signal_receiver(lambda *values: leaked.append(values), signal_name='GuidanceChanged',
                                    dbus_interface=NAVIGATION_INTERFACE)
    try:
        provider = example.FakeNavigation('org.example.Navigation', 'example-navigation', loop, stay_alive=True)
        providers.append(provider)
        finished, errors = [], []
        car = NavigationClient('org.example.Navigation', on_request=lambda *values: finished.append(values),
                               on_error=lambda *values: errors.append(values))
        phone = NavigationClient('org.example.Navigation', presentation='phone')
        clients.extend((car, phone))
        car.open()
        phone.open()
        wait(lambda: car.ready and phone.ready)
        assert provider.backend.session_count == 2 and provider.backend.active_session_count == 2
        xml = call(car.bus, car._owner, car.session_path, 'org.freedesktop.DBus.Introspectable', 'Introspect')[0]
        actual = ET.fromstring(str(xml)).find("interface[@name='{}']".format(NAVIGATION_INTERFACE))
        expected = ET.fromstring(interface_xml(NAVIGATION_INTERFACE)).find('interface')
        assert ET.tostring(actual) == ET.tostring(expected), xml
        revision, value = call(car.bus, car._owner, car.session_path, NAVIGATION_INTERFACE, 'GetGuidance')
        assert value['state'] == 'idle' and int(revision) == car.revision
        call(spy, car._owner, car.session_path, NAVIGATION_INTERFACE, 'GetGuidance',
             error='org.sailplay.Error1.NotOwner')
        call(car.bus, car._owner, car.session_path, NAVIGATION_INTERFACE, 'GetGuidance', 's', ('unexpected',),
             error='org.freedesktop.DBus.Error.InvalidArgs')
        car.invoke('navigation.start')
        wait(lambda: bool(finished) and phone.guidance.get('state') == 'active')
        assert not errors and not finished[-1][3]
        phone.close()
        wait(lambda: provider.backend.session_count == 1)
        before = car.revision
        wait(lambda: car.revision > before)
        assert provider.active and car.guidance['state'] == 'active'
        car.set_active(False)
        wait(lambda: provider.backend.active_session_count == 0)
        assert provider.active
        call(car.bus, car._owner, car.session_path, SESSION_INTERFACE, 'SetActive', 'b', (True,))
        assert provider.backend.active_session_count == 1
        # An accepted stop belongs to the backend after its requesting view closes.
        car.invoke('navigation.stop', {'delayMs': 250})
        wait(lambda: provider.backend.pending_count == 1)
        car.close()
        wait(lambda: provider.backend.session_count == 0)
        assert provider.backend.pending_count == 1
        wait(lambda: provider.backend.pending_count == 0 and not provider.active)
        assert provider.backend.model.state['navigation']['state'] == 'stopped'
        assert not leaked, 'Guidance was broadcast to unrelated callers'

        resident = NavigationClient('org.example.Navigation')
        clients.append(resident)
        resident.open()
        wait(lambda: resident.ready)
        old_instance = resident.instance_id
        provider.close()
        wait(lambda: not resident.ready and not resident.guidance)
        replacement = example.FakeNavigation('org.example.Navigation', 'example-navigation', loop, stay_alive=True)
        providers.append(replacement)
        wait(lambda: resident.ready)
        assert resident.instance_id != old_instance and resident.guidance['state'] == 'idle'
        assert not replacement.active, 'Reconnect restarted stopped navigation'

        second = example.FakeNavigation('org.example.AnotherMap', 'another-map', loop, stay_alive=True)
        providers.append(second)
        second_client = NavigationClient('org.example.AnotherMap')
        clients.append(second_client)
        second_client.open()
        wait(lambda: second_client.ready)
        second.backend.publish_guidance(guidance('active', maneuver='turn-right', currentRoad='道路', nextRoad='Next'))
        wait(lambda: second_client.guidance.get('maneuver') == 'turn-right')
        assert resident.guidance['state'] == 'idle'
        crashed = NavigationClient('org.example.AnotherMap')
        clients.append(crashed)
        crashed.open()
        wait(lambda: crashed.ready and second.backend.session_count == 2)
        crashed.bus.close()
        wait(lambda: second.backend.session_count == 1)
        reference_service = 'org.example.NavigationReference'
        reference = subprocess.Popen([sys.executable, '-B', str(EXAMPLES / 'navigation-service.py'),
            '--service', reference_service, '--application-id', 'navigation-reference', '--active', '--stay-alive'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        wait(lambda: spy.name_has_owner(reference_service))
        reference_client = NavigationClient(reference_service)
        clients.append(reference_client)
        reference_client.open()
        wait(lambda: reference_client.ready and reference_client.guidance.get('state') == 'active')
        reference_client.close()
        reference.terminate()
        output, errors = reference.communicate(timeout=5)
        assert reference.returncode == 0 and 'NAVIGATION_READY ' in output, (output, errors)
        print('NAVIGATION_SDK_BUS_PASS ' + json.dumps({'phone_close_preserved_route': True,
              'hidden_view_preserved_route': True, 'accepted_stop_completed': True,
              'fresh_restart_snapshot': True, 'second_provider': True, 'owner_loss_released_session': True,
              'reference_main_and_signal_exit': True}))
    finally:
        if reference is not None and reference.poll() is None:
            reference.terminate()
            try:
                reference.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                reference.kill()
                reference.communicate(timeout=3)
        for client in clients:
            client.close()
        for provider in providers:
            provider.close()
        match.remove()
        spy.close()


if __name__ == '__main__':
    main()
