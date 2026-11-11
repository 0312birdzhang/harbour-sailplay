import errno
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from android_auto.network import NetworkHandover
from carplay_proto.networksession import restore_network


class InProgress(Exception):
    def get_dbus_name(self):
        return 'net.connman.Error.InProgress'


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
                                                   [('/car', {'State': state})]]
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
        manager.GetServices.side_effect = [[('/old', {'State': state})] for state in ('idle', 'association', 'online')]
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
        manager.GetServices.side_effect = [[('/old', {'State': 'idle'})], [('/old', {'State': 'failure'})]]
        service.Connect.side_effect = InProgress()
        with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: path), \
                patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: manager if obj == '/' else service), \
                self.assertRaises(RuntimeError):
            restore_network(lease, None, log=Mock())
        lease.network_restored.assert_not_called()


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
