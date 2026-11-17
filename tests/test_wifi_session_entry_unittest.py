import importlib.util
import json
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from carplay_proto import networkdbus, networksession, networktrace, runtime_logging, wifidiscovery
from carplay_proto.session import SessionLease, current_owner


source_path = Path(__file__).resolve().parents[1] / 'scripts' / 'wifi-session-probe.py'
spec = importlib.util.spec_from_file_location('wifi_session_entry_probe', source_path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class WifiSessionEntryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lock_path = directory.name + '/lock'
        self.lease = SessionLease('carplay', self.lock_path, None)
        self.addCleanup(self.lease.close)
        self.session_path = Path(directory.name) / 'session.json'
        self.session = {'ssid': 'CurrentHU', 'passphrase': 'current-bluetooth-password',
                        'security': 1, 'channel': 36, 'addresses': ['192.168.44.1'],
                        'port': 7000, 'device_name': 'Fixture phone'}
        self.session_path.write_text(json.dumps(self.session), encoding='utf-8')
        self.properties = {'Type': 'wifi', 'Name': 'CurrentHU', 'State': 'idle',
                           'Favorite': False, 'Strength': 60,
                           'IPv4.Configuration': {'Method': 'dhcp'}}
        self.home_properties = {'Type': 'wifi', 'Name': 'Home', 'State': 'idle', 'Favorite': True}
        self.retired_properties = {'Type': 'wifi', 'Name': 'RetiredHU', 'State': 'ready', 'Favorite': True}
        self.services = [('/current-car', self.properties)]
        self.events, self.callbacks = [], []
        self.manager, self.car, self.home, self.retired, self.technology, self.loop = [Mock() for _ in range(6)]
        self.manager.GetServices.side_effect = lambda **kwargs: self.services
        self.manager.GetTechnologies.return_value = [('/wifi', {'Type': 'wifi', 'Powered': True})]
        self.car.GetProperties.side_effect = lambda: self.properties
        self.car.Connect.side_effect = self.connect_car
        self.car.Disconnect.side_effect = lambda: self.properties.update(State='idle')
        self.retired.Disconnect.side_effect = lambda: self.retired_properties.update(State='idle')
        self.home.Connect.side_effect = lambda **kwargs: self.events.append('connect-home')
        self.systemd = Mock()
        self.systemd.ListUnits.return_value = []
        self.objects = {'/': self.manager, '/current-car': self.car, '/home': self.home,
                        '/retired-car': self.retired, '/wifi': self.technology,
                        '/org/freedesktop/systemd1': self.systemd,
                        '/org/freedesktop/DBus': Mock()}

    def connect_car(self, **kwargs):
        self.events.append('connect-current-car')
        self.home_properties['State'] = 'idle'
        self.properties.update(State='association', Favorite=True)

    def run_entry(self, arguments=None):
        class AgentObject:
            def __init__(self, *args):
                pass

            def remove_from_connection(self):
                pass

        service_api = SimpleNamespace(Object=AgentObject, method=lambda *args, **kwargs: lambda method: method)
        dbus_api = SimpleNamespace(service=service_api, SystemBus=Mock(), ObjectPath=str,
                                   String=lambda value, **kwargs: value,
                                   Boolean=lambda value, **kwargs: value, DBusException=RuntimeError)
        glib_api = Mock()
        glib_api.MainLoop.return_value = self.loop
        modules = {'dbus': dbus_api, 'dbus.service': service_api,
                   'dbus.mainloop': SimpleNamespace(),
                   'dbus.mainloop.glib': SimpleNamespace(DBusGMainLoop=Mock()),
                   'gi': SimpleNamespace(), 'gi.repository': SimpleNamespace(GLib=glib_api)}
        if arguments is None:
            arguments = ['--connect', '--direct-passphrase', '--sustained', '--session', str(self.session_path)]
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, modules))
            stack.enter_context(patch.object(sys, 'argv', [str(source_path)] + arguments))
            stack.enter_context(patch('carplay_proto.session.SessionLease', return_value=self.lease))
            stack.enter_context(patch('carplay_proto.session.current_owner',
                                     side_effect=lambda path=self.lock_path: current_owner(path)))
            for module in (networksession, networkdbus):
                stack.enter_context(patch.object(module, 'network_object',
                                         side_effect=lambda bus, name, path, **kwargs: self.objects[path]))
                stack.enter_context(patch.object(module, 'network_interface', side_effect=lambda obj, name: obj))
            stack.enter_context(patch.object(wifidiscovery, 'discover',
                                     side_effect=lambda *args, **kwargs: ('/current-car', self.services)))
            stack.enter_context(patch.object(networktrace, 'NetworkTrace'))
            for name in ('persist_output', 'log_to_stdout', 'collection_enabled'):
                stack.enter_context(patch.object(runtime_logging, name, return_value=False))
            launches = stack.enter_context(patch.object(probe.subprocess, 'run'))
            stack.enter_context(patch.object(probe.atexit, 'register', side_effect=self.callbacks.append))
            stack.enter_context(patch.object(probe.time, 'sleep'))
            messages = stack.enter_context(patch('builtins.print'))
            try:
                probe.main()
            finally:
                for callback in reversed(self.callbacks):
                    callback()
            self.launches = launches.call_args_list
            self.messages = [str(call[0][0]) for call in messages.call_args_list]

    def assert_current_hu_connected(self):
        self.car.SetProperty.assert_called_with('Passphrase', self.session['passphrase'])
        self.car.Connect.assert_called_once()
        self.assertEqual(self.events[0], 'connect-current-car')
        self.assertNotIn(self.session['passphrase'], '\n'.join(self.messages))
        command = self.launches[0][0][0]
        self.assertEqual(command[command.index('--restore') + 2], '/current-car')
        self.assertEqual(command[command.index('--session-id') + 1], self.lease.identity)

    def test_empty_wifi_history_connects_with_current_bluetooth_credentials(self):
        self.run_entry()
        self.assert_current_hu_connected()
        command = self.launches[0][0][0]
        self.assertEqual(command[command.index('--restore') + 1], '')
        self.home.Connect.assert_not_called()
        self.car.Disconnect.assert_called_once()
        self.car.Remove.assert_called_once()
        self.assertIsNone(current_owner(self.lock_path)['network'])

    def test_idle_saved_hotspot_is_optional_when_connecting_the_current_hu(self):
        self.services.insert(0, ('/home', self.home_properties))
        self.run_entry()
        self.assert_current_hu_connected()
        self.home.Connect.assert_not_called()

    def test_current_home_wifi_reconnects_after_the_hu_attempt_ends(self):
        self.home_properties['State'] = 'online'
        self.services.insert(0, ('/home', self.home_properties))
        self.run_entry()
        self.assert_current_hu_connected()
        self.assertEqual(self.events, ['connect-current-car', 'connect-home'])
        self.home.Connect.assert_called_once_with(timeout=20)

    def test_inherited_restore_failure_allows_the_new_hu_connection(self):
        with SessionLease('carplay', self.lock_path, None) as previous:
            previous.plan_network('/home', '/retired-car', forget=True)
        self.services.extend([('/home', self.home_properties), ('/retired-car', self.retired_properties)])

        def failed_restore(**kwargs):
            self.events.append('connect-home')
            raise RuntimeError('previous hotspot is unavailable')

        self.home.Connect.side_effect = failed_restore
        self.run_entry()
        self.assert_current_hu_connected()
        self.retired.Disconnect.assert_called_once()
        self.retired.Remove.assert_called_once()
        self.assertEqual(self.events, ['connect-current-car', 'connect-home'])
        self.assertEqual(current_owner(self.lock_path)['network']['old'], '/home')

    def test_empty_history_connects_after_enabling_wifi(self):
        self.manager.GetTechnologies.return_value = [('/wifi', {'Type': 'wifi', 'Powered': False})]
        self.run_entry()
        self.assert_current_hu_connected()
        self.technology.SetProperty.assert_called_once_with('Powered', True)

    def test_disconnected_hu_from_the_previous_plan_is_connected_again(self):
        with SessionLease('carplay', self.lock_path, None) as previous:
            previous.plan_network('/current-car', '/retired-car')
        self.run_entry()
        self.assert_current_hu_connected()

    def test_existing_current_hu_connection_is_reused(self):
        self.properties['State'] = 'ready'
        self.run_entry()
        self.car.Connect.assert_not_called()
        self.car.SetProperty.assert_not_called()
        self.car.Disconnect.assert_not_called()
        self.assertEqual(self.launches, [])

    def test_recovery_timer_accepts_an_empty_previous_wifi(self):
        self.properties.update(State='ready', Favorite=True)
        self.lease.acquire()
        self.lease.plan_network(None, '/current-car', forget=True)
        self.lease.close()
        self.run_entry(['--restore', '', '/current-car', '--restore-after', '10',
                        '--session-id', self.lease.identity])
        self.home.Connect.assert_not_called()
        self.car.Disconnect.assert_called_once()
        self.car.Remove.assert_called_once()
        self.assertIsNone(current_owner(self.lock_path)['network'])


if __name__ == '__main__':
    unittest.main()
