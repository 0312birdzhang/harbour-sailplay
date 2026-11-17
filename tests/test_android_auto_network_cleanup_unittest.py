import errno
from contextlib import ExitStack
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from android_auto.network import NetworkHandover
from android_auto.protobuf import field
from android_auto.wireless import Credentials
from carplay_proto.networksession import restore_network, restore_previous_network
from carplay_proto.session import SessionLease, current_owner


class InProgress(Exception):
    def get_dbus_name(self):
        return 'net.connman.Error.InProgress'


class NoCarrier(Exception):
    def get_dbus_name(self):
        return 'net.connman.Error.NoCarrier'


class ConnectFailed(Exception):
    def get_dbus_name(self):
        return 'net.connman.Error.Failed'


class NetworkCleanupTests(unittest.TestCase):
    def test_disconnected_unremembered_target_clears_the_recovery_journal(self):
        for state in ('idle', 'failure', 'disconnect'):
            with self.subTest(state=state):
                lease = SimpleNamespace(state={'network': {'old': '/old', 'target': '/car', 'forget': True}},
                                        phase=Mock(), network_restored=Mock())
                manager, service = Mock(), Mock()
                manager.GetServices.return_value = [('/old', {'State': 'online'}),
                    ('/car', {'State': state, 'Favorite': False})]
                with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: path), \
                        patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: manager if obj == '/' else service):
                    restore_network(lease, None, log=Mock())
                service.Disconnect.assert_not_called()
                service.Remove.assert_not_called()
                lease.network_restored.assert_called_once()

    def test_target_disconnect_race_requires_confirmation_of_disconnected_state(self):
        class NotSupported(Exception):
            def get_dbus_name(self):
                return 'net.connman.Error.NotSupported'
        for state in ('idle', 'ready'):
            with self.subTest(state=state):
                lease = SimpleNamespace(state={'network': {'old': '/old', 'target': '/car'}},
                                        phase=Mock(), network_restored=Mock())
                manager, service = Mock(), Mock()
                manager.GetServices.side_effect = [[('/old', {'State': 'online'}), ('/car', {'State': 'ready'})],
                                                   [('/car', {'State': state})],
                                                   [('/old', {'State': 'online'}), ('/car', {'State': state})]]
                service.Disconnect.side_effect = NotSupported()
                with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: path), \
                        patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: manager if obj == '/' else service):
                    if state == 'ready':
                        with self.assertRaises(NotSupported):
                            restore_network(lease, None, log=Mock())
                        lease.network_restored.assert_not_called()
                    else:
                        restore_network(lease, None, log=Mock())
                        lease.network_restored.assert_called_once()

    def test_agent_unregister_uses_dbus_object_path(self):
        class ObjectPath(str):
            pass
        handover = NetworkHandover.__new__(NetworkHandover)
        handover.agent, handover.manager = Mock(), Mock()
        handover.agent_path, handover.lease, handover.bus, handover.log = '/org/sailplay/agent', Mock(), Mock(), Mock()
        agent = handover.agent
        with patch.dict(sys.modules, dbus=SimpleNamespace(ObjectPath=ObjectPath)), \
                patch('android_auto.network.restore_network') as restore:
            handover.close()
        self.assertIsInstance(handover.manager.UnregisterAgent.call_args[0][0], ObjectPath)
        agent.remove_from_connection.assert_called_once()
        restore.assert_called_once()
        self.assertIsNone(handover.agent)

    def test_in_progress_restore_waits_for_the_original_network(self):
        lease = SimpleNamespace(state={'network': {'old': '/old', 'target': None}}, phase=Mock(), network_restored=Mock())
        manager, service = Mock(), Mock()
        manager.GetServices.side_effect = [[('/old', {'State': state})] for state in ('idle', 'idle', 'association', 'online')]
        service.Connect.side_effect = InProgress()
        with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: path), \
                patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: manager if obj == '/' else service), \
                patch('carplay_proto.networksession.time.sleep'):
            restore_network(lease, None, log=Mock())
        service.Connect.assert_called_once_with(timeout=20)
        lease.network_restored.assert_called_once()

    def test_failed_restore_retains_the_network_journal(self):
        lease = SimpleNamespace(state={'network': {'old': '/old', 'target': None}}, phase=Mock(), network_restored=Mock())
        manager, service = Mock(), Mock()
        manager.GetServices.side_effect = [[('/old', {'State': 'idle'})], [('/old', {'State': 'idle'})],
                                          [('/old', {'State': 'failure'})]]
        service.Connect.side_effect = InProgress()
        with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: path), \
                patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: manager if obj == '/' else service), \
                self.assertRaises(RuntimeError):
            restore_network(lease, None, log=Mock())
        lease.network_restored.assert_not_called()

    def test_unavailable_original_network_is_not_inherited_by_the_next_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/lock'
            manager, old, technology = Mock(), Mock(), Mock()
            manager.GetServices.return_value = [('/old', {'Type': 'wifi', 'State': 'idle'})]
            old.Connect.side_effect = NoCarrier()
            objects = {'/': manager, '/old': old, '/wifi': technology}
            messages = []
            with SessionLease('carplay', path, None) as lease:
                lease.plan_network('/old', '/car', forget=True, wifi_path='/wifi', powered=False)
                with patch.dict(sys.modules, dbus=SimpleNamespace(Boolean=lambda value, **kwargs: value)), \
                        patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: objects[path]), \
                        patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: obj):
                    restore_network(lease, None, log=messages.append)
                self.assertIsNone(current_owner(path)['network'])
            old.Connect.assert_called_once_with(timeout=20)
            technology.SetProperty.assert_called_once_with('Powered', False)
            self.assertIn('Previous Wi-Fi network unavailable, retiring its restoration request', messages)
            with SessionLease('carplay', path, None) as next_session:
                self.assertIsNone(next_session.state['network'])

    def test_failed_original_reconnect_retires_the_inherited_network_plan(self):
        for protocol in ('carplay', 'android-auto'):
            with self.subTest(protocol=protocol), tempfile.TemporaryDirectory() as directory:
                path = directory + '/lock'
                with SessionLease('carplay', path, None) as previous_session:
                    previous_session.plan_network('/old', '/car', forget=True)
                manager, old, car, systemd = Mock(), Mock(), Mock(), Mock()
                manager.GetServices.return_value = [('/old', {'Type': 'wifi', 'State': 'idle'}),
                                                   ('/car', {'Type': 'wifi', 'State': 'ready', 'Favorite': True})]
                old.Connect.side_effect = ConnectFailed('Input/output error')
                systemd.ListUnits.return_value = []
                objects = {'/': manager, '/old': old, '/car': car,
                           '/org/freedesktop/systemd1': systemd}
                with SessionLease(protocol, path, None) as lease:
                    self.assertEqual(lease.state['network']['old'], '/old')
                    with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: objects[path]), \
                            patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: obj):
                        restore_previous_network(lease, None, log=Mock())
                    self.assertIsNone(current_owner(path)['network'])
                    lease.phase('connecting')
                    self.assertEqual(current_owner(path)['phase'], 'connecting')
                car.Disconnect.assert_called_once()
                car.Remove.assert_called_once()
                old.Connect.assert_called_once_with(timeout=20)
                with SessionLease(protocol, path, None) as next_session:
                    self.assertIsNone(next_session.state['network'])

    def test_connection_preparation_defers_the_original_wifi_reconnect_and_power_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/lock'
            with SessionLease('android-auto', path, None) as previous:
                previous.plan_network('/old', '/car', forget=True, wifi_path='/wifi', powered=False)
            manager, old, car, technology, systemd = Mock(), Mock(), Mock(), Mock(), Mock()
            car_properties = {'Type': 'wifi', 'State': 'ready', 'Favorite': True}
            manager.GetServices.return_value = [('/old', {'Type': 'wifi', 'State': 'idle'}),
                                               ('/car', car_properties)]
            car.Disconnect.side_effect = lambda: car_properties.update(State='idle')
            systemd.ListUnits.return_value = []
            objects = {'/': manager, '/old': old, '/car': car, '/wifi': technology,
                       '/org/freedesktop/systemd1': systemd}
            with SessionLease('carplay', path, None) as lease:
                with patch.dict(sys.modules, dbus=SimpleNamespace(Boolean=lambda value, **kwargs: value)), \
                        patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: objects[path]), \
                        patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: obj):
                    restore_previous_network(lease, None, log=Mock(), reconnect=False)
                    old.Connect.assert_not_called()
                    technology.SetProperty.assert_not_called()
                    plan = current_owner(path)['network']
                    self.assertEqual(plan['old'], '/old')
                    self.assertIsNone(plan['target'])
                    self.assertEqual(plan['wifi_path'], '/wifi')
                    self.assertFalse(plan['powered'])
                    car.Disconnect.assert_called_once()
                    car.Remove.assert_called_once()
                    restore_network(lease, None, log=Mock())
                old.Connect.assert_called_once_with(timeout=20)
                technology.SetProperty.assert_called_once_with('Powered', False)
                self.assertIsNone(current_owner(path)['network'])

    def test_connection_preparation_retires_the_legacy_job_and_defers_home_reconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            old_path, car_path = '/net/connman/service/wifi_home', '/net/connman/service/wifi_car'
            unit_name = 'sailplay-wifi-restore-101.service'
            arguments = ['python3', '/opt/sailplay/scripts/wifi-session-probe.py',
                         '--restore', old_path, car_path, '--restore-after', '45']
            unit_values = {'ExecStart': [('python3', arguments)], 'ExecMainStartTimestampMonotonic': 100}
            unit = SimpleNamespace(Get=Mock(side_effect=lambda interface, name, **kwargs: unit_values[name]))
            systemd, manager, old, car = Mock(), Mock(), Mock(), Mock()
            systemd.ListUnits.return_value = [(unit_name, '', 'loaded', 'active', 'running', '', '/legacy')]
            manager.GetServices.return_value = [(old_path, {'Type': 'wifi', 'State': 'idle'}),
                                               (car_path, {'Type': 'wifi', 'State': 'ready', 'Favorite': True})]
            objects = {'/org/freedesktop/systemd1': systemd, '/legacy': unit, '/': manager,
                       old_path: old, car_path: car}
            with SessionLease('carplay', directory + '/lock', None) as lease:
                with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: objects[path]), \
                        patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: obj), \
                        patch('carplay_proto.networksession.subprocess.run') as stop:
                    restore_previous_network(lease, None, log=Mock(), reconnect=False)
                stop.assert_called_once_with(['systemctl', 'stop', unit_name], check=True, timeout=20)
                car.Disconnect.assert_called_once()
                car.Remove.assert_not_called()
                old.Connect.assert_not_called()
                self.assertEqual(current_owner(lease.lock_path)['network']['old'], old_path)
                self.assertIsNone(current_owner(lease.lock_path)['network']['target'])

    def test_current_wifi_connection_supersedes_the_original_network_and_power_state(self):
        lease = SimpleNamespace(state={'network': {'old': '/old', 'target': '/car', 'forget': True,
                                                   'wifi_path': '/wifi', 'powered': False}},
                                phase=Mock(), network_restored=Mock())
        manager, old, car, technology = Mock(), Mock(), Mock(), Mock()
        manager.GetServices.return_value = [('/old', {'Type': 'wifi', 'State': 'idle'}),
                                           ('/car', {'Type': 'wifi', 'State': 'idle', 'Favorite': True}),
                                           ('/current', {'Type': 'wifi', 'State': 'online'})]
        objects = {'/': manager, '/old': old, '/car': car, '/wifi': technology}
        with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: objects[path]), \
                patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: obj):
            restore_network(lease, None, log=Mock())
        old.Connect.assert_not_called()
        car.Disconnect.assert_not_called()
        car.Remove.assert_called_once()
        technology.SetProperty.assert_not_called()
        lease.network_restored.assert_called_once()

    def test_current_wifi_selected_during_target_cleanup_is_preserved(self):
        lease = SimpleNamespace(state={'network': {'old': '/old', 'target': '/car'}},
                                phase=Mock(), network_restored=Mock())
        manager, old, car = Mock(), Mock(), Mock()
        manager.GetServices.side_effect = [
            [('/old', {'Type': 'wifi', 'State': 'idle'}), ('/car', {'Type': 'wifi', 'State': 'ready'})],
            [('/old', {'Type': 'wifi', 'State': 'idle'}), ('/current', {'Type': 'wifi', 'State': 'ready'})]]
        objects = {'/': manager, '/old': old, '/car': car}
        with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: objects[path]), \
                patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: obj):
            restore_network(lease, None, log=Mock())
        car.Disconnect.assert_called_once()
        old.Connect.assert_not_called()
        lease.network_restored.assert_called_once()

    def test_unavailable_target_disconnect_retains_the_recovery_journal(self):
        lease = SimpleNamespace(state={'network': {'old': '/old', 'target': '/car'}},
                                phase=Mock(), network_restored=Mock())
        manager, old, car = Mock(), Mock(), Mock()
        manager.GetServices.return_value = [('/old', {'Type': 'wifi', 'State': 'idle'}),
                                           ('/car', {'Type': 'wifi', 'State': 'ready'})]
        car.Disconnect.side_effect = NoCarrier()
        objects = {'/': manager, '/old': old, '/car': car}
        with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: objects[path]), \
                patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: obj), \
                self.assertRaises(NoCarrier):
            restore_network(lease, None, log=Mock())
        old.Connect.assert_not_called()
        lease.network_restored.assert_not_called()

    def test_unexpected_original_network_error_retains_the_recovery_journal(self):
        lease = SimpleNamespace(state={'network': {'old': '/old', 'target': None}},
                                phase=Mock(), network_restored=Mock())
        manager, old = Mock(), Mock()
        manager.GetServices.return_value = [('/old', {'Type': 'wifi', 'State': 'idle'})]
        error = RuntimeError('ConnMan service unavailable')
        error.get_dbus_name = lambda: 'org.freedesktop.DBus.Error.ServiceUnknown'
        old.Connect.side_effect = error
        objects = {'/': manager, '/old': old}
        with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: objects[path]), \
                patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: obj), \
                self.assertRaises(RuntimeError):
            restore_network(lease, None, log=Mock())
        lease.network_restored.assert_not_called()


class NetworkHandoverRetryTests(unittest.TestCase):
    def setUp(self):
        class AgentObject:
            def __init__(self, *args):
                pass

            def remove_from_connection(self):
                pass

        service_api = SimpleNamespace(Object=AgentObject, method=lambda *args, **kwargs: lambda method: method)
        dbus_api = SimpleNamespace(service=service_api, ObjectPath=str, String=lambda value, **kwargs: value,
                                   Boolean=lambda value, **kwargs: value)
        self.properties = {'Type': 'wifi', 'Name': 'DiAutoAP', 'Favorite': True, 'State': 'idle', 'Strength': 60,
                           'IPv4.Configuration': {'Method': 'dhcp'}, 'Ethernet': {'Interface': 'wlan0'}}
        self.manager, self.target, self.technology = Mock(), Mock(), Mock()
        self.manager.GetTechnologies.return_value = [('/wifi', {'Type': 'wifi', 'Powered': True})]
        self.manager.GetServices.return_value = [('/home', {'Type': 'wifi', 'State': 'ready'}), ('/car', self.properties)]
        self.target.GetProperties.side_effect = lambda: self.properties
        self.credentials = Credentials(('192.168.44.1', 5288), field(1, 'DiAutoAP') + field(2, 'test-passphrase'))
        self.lease = SimpleNamespace(identity='retry-test', plan_network=Mock(), network_restored=Mock())
        self.stop, self.messages, self.now = threading.Event(), [], 0.0
        objects = {'/': self.manager, '/car': self.target, '/wifi': self.technology}
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(sys.modules, {'dbus': dbus_api, 'dbus.service': service_api}))
        stack.enter_context(patch('android_auto.network.network_object', side_effect=lambda bus, name, path: objects[path]))
        stack.enter_context(patch('android_auto.network.network_interface', side_effect=lambda obj, name: obj))
        stack.enter_context(patch('android_auto.network.associated_network', return_value=('DiAutoAP', None)))
        stack.enter_context(patch('android_auto.network.time.monotonic', side_effect=lambda: self.now))
        stack.enter_context(patch.object(self.stop, 'wait', side_effect=self.wait))
        self.restore = stack.enter_context(patch('android_auto.network.restore_network'))
        self.handover = NetworkHandover(self.lease, None, self.stop, self.messages.append)

    def wait(self, seconds):
        self.now += seconds
        return self.stop.is_set()

    def ready(self, **kwargs):
        self.properties.update(State='ready', IPv4={'Address': '192.168.44.2'})
        kwargs['reply_handler']()

    def test_io_error_retries_the_same_session_and_restores_its_network_plan(self):
        error = ConnectFailed('Input/output error')

        def first_attempt(**kwargs):
            self.properties.update(State='failure', Error='connect-failed')
            kwargs['error_handler'](error)

        attempts = [first_attempt, self.ready]
        self.target.Connect.side_effect = lambda **kwargs: attempts.pop(0)(**kwargs)
        self.assertEqual(self.handover.connect(self.credentials), ('wlan0', '192.168.44.2'))
        self.assertEqual(self.target.Connect.call_count, 2)
        self.technology.Scan.assert_called_once()
        self.manager.RegisterAgent.assert_called_once()
        self.assertEqual(self.lease.plan_network.call_count, 2)
        self.lease.plan_network.assert_called_with('/home', '/car', forget=False, wifi_path='/wifi', powered=True)
        self.assertIn('dbusError=net.connman.Error.Failed state=failure', '\n'.join(self.messages))
        self.assertNotIn(self.credentials.password, '\n'.join(self.messages))
        self.handover.close()
        self.assertEqual(self.restore.call_count, 2)
        self.manager.UnregisterAgent.assert_called_once()

    def test_repeated_carrier_failures_stop_after_three_attempts(self):
        error = NoCarrier('carrier not ready')
        self.target.Connect.side_effect = lambda **kwargs: kwargs['error_handler'](error)
        with self.assertRaises(NoCarrier) as failure:
            self.handover.connect(self.credentials)
        self.assertIs(failure.exception, error)
        self.assertEqual(self.target.Connect.call_count, 3)
        self.assertEqual(self.technology.Scan.call_count, 2)
        timeouts = [call.kwargs['timeout'] for call in self.target.Connect.call_args_list]
        self.assertEqual(timeouts[0], 40)
        self.assertGreater(timeouts[0], timeouts[1])
        self.assertGreater(timeouts[1], timeouts[2])

    def test_invalid_credentials_fail_without_retrying(self):
        self.properties['Error'] = 'invalid-key'
        self.target.Connect.side_effect = lambda **kwargs: kwargs['error_handler'](ConnectFailed())
        with self.assertRaises(ConnectFailed):
            self.handover.connect(self.credentials)
        self.target.Connect.assert_called_once()
        self.technology.Scan.assert_not_called()

    def test_agent_authentication_error_is_logged_and_prevents_retry(self):
        def rejected(**kwargs):
            self.handover.agent.ReportError('/car', 'invalid-key')
            kwargs['error_handler'](ConnectFailed())

        self.target.Connect.side_effect = rejected
        with self.assertRaises(ConnectFailed):
            self.handover.connect(self.credentials)
        self.target.Connect.assert_called_once()
        self.technology.Scan.assert_not_called()
        self.assertIn('Android Auto Wi-Fi agent reported error=invalid-key', self.messages)

    def test_stop_during_retry_delay_prevents_scan_and_reconnect(self):
        self.target.Connect.side_effect = lambda **kwargs: kwargs['error_handler'](ConnectFailed())
        self.stop.wait.side_effect = lambda seconds: (self.stop.set(), True)[1]
        with self.assertRaises(InterruptedError):
            self.handover.connect(self.credentials)
        self.target.Connect.assert_called_once()
        self.technology.Scan.assert_not_called()

    def test_retry_scan_uses_the_remaining_deadline(self):
        self.target.Connect.side_effect = lambda **kwargs: kwargs['error_handler'](ConnectFailed())

        def scan(**kwargs):
            self.now += kwargs['timeout']

        self.technology.Scan.side_effect = scan
        with self.assertRaises(TimeoutError):
            self.handover.connect(self.credentials, timeout=3)
        self.assertEqual(self.now, 3)
        self.target.Connect.assert_called_once()
        self.technology.Scan.assert_called_once_with(timeout=1)

    def test_in_progress_connection_is_observed_until_association(self):
        self.target.Connect.side_effect = lambda **kwargs: kwargs['error_handler'](InProgress())

        def wait_until_ready(seconds):
            self.now += seconds
            self.properties.update(State='ready', IPv4={'Address': '192.168.44.2'})
            return False

        self.stop.wait.side_effect = wait_until_ready
        self.assertEqual(self.handover.connect(self.credentials), ('wlan0', '192.168.44.2'))
        self.target.Connect.assert_called_once()
        self.technology.Scan.assert_not_called()


class NetworkEndpointTests(unittest.TestCase):
    def setUp(self):
        self.handover = NetworkHandover.__new__(NetworkHandover)
        self.handover.stop, self.handover.log = threading.Event(), Mock()
        self.credentials = SimpleNamespace(address='192.168.49.1', port=5288)

    def test_temporary_route_failure_retries_on_the_same_interface(self):
        sock = Mock()
        with patch('android_auto.network.connect_endpoint', side_effect=[OSError(errno.EHOSTUNREACH, 'route pending'), sock]) as connect, \
                patch.object(self.handover.stop, 'wait'):
            self.assertIs(self.handover.endpoint(self.credentials, 'wlan0'), sock)
        self.assertEqual(connect.call_count, 2)
        self.assertTrue(all(call.args == ('192.168.49.1', 5288, 'wlan0') for call in connect.call_args_list))

    def test_stop_interrupts_endpoint_recovery(self):
        with patch('android_auto.network.connect_endpoint', side_effect=OSError(errno.ECONNREFUSED, 'server starting')) as connect, \
                patch.object(self.handover.stop, 'wait', side_effect=lambda seconds: self.handover.stop.set()), \
                self.assertRaises(InterruptedError):
            self.handover.endpoint(self.credentials, 'wlan0')
        connect.assert_called_once()

    def test_permanent_endpoint_failure_is_not_retried(self):
        with patch('android_auto.network.connect_endpoint', side_effect=OSError(errno.EACCES, 'denied')) as connect, \
                self.assertRaises(PermissionError):
            self.handover.endpoint(self.credentials, 'wlan0')
        connect.assert_called_once()

    def test_endpoint_recovery_is_bounded(self):
        with patch('android_auto.network.connect_endpoint', side_effect=OSError(errno.EHOSTUNREACH, 'route pending')) as connect, \
                patch('android_auto.network.time.monotonic', side_effect=[0, 0, 31, 31]), \
                patch.object(self.handover.stop, 'wait'), self.assertRaises(TimeoutError):
            self.handover.endpoint(self.credentials, 'wlan0')
        connect.assert_called_once()
