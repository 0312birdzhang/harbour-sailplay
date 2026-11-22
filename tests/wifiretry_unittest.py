import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from carplay_proto.wifiretry import ReassociationWindow, reassociate_target, HandoverRetry, mixed_wpa_security


class RetryTests(unittest.TestCase):
    def test_wpa2_compatibility_requires_mixed_psk_and_sae(self):
        self.assertTrue(mixed_wpa_security({'key_mgmt':'WPA-PSK WPA-PSK-SHA256 SAE'}))
        for value in ('SAE', 'WPA-PSK', 'WPA-EAP', 'NONE', ''):
            self.assertFalse(mixed_wpa_security({'key_mgmt':value}))
        self.assertFalse(mixed_wpa_security({}))

    def test_failed_handover_retries_without_new_bluetooth_connection(self):
        now = [100]
        launch = Mock()
        retry = HandoverRetry(lambda: False, launch, clock=lambda: now[0])
        self.assertFalse(retry.poll())
        retry.arm()
        now[0] = 109
        self.assertFalse(retry.poll())
        now[0] = 110
        self.assertTrue(retry.poll())
        self.assertFalse(retry.poll())
        launch.assert_called_once_with()
        now[0] = 129
        self.assertFalse(retry.poll())
        now[0] = 130
        self.assertTrue(retry.poll())
        self.assertEqual(launch.call_count, 2)

    def test_repeated_failures_back_off_to_a_bounded_interval(self):
        now = [0]
        launches = []
        retry = HandoverRetry(lambda: False, lambda: launches.append(now[0]), clock=lambda: now[0])
        retry.arm()
        for now[0] in range(1, 181):
            retry.poll()
        self.assertEqual(launches, [10, 30, 70, 130])
        self.assertEqual(retry.delay(), 60)

    def test_active_media_resets_the_backoff(self):
        now = [0]
        active, launch = Mock(return_value=False), Mock()
        retry = HandoverRetry(active, launch, clock=lambda: now[0])
        retry.arm()
        for now[0] in (10, 30):
            self.assertTrue(retry.poll())
        active.return_value = True
        now[0] = 70
        self.assertFalse(retry.poll())
        active.return_value = False
        now[0] = 79
        self.assertFalse(retry.poll())
        now[0] = 80
        self.assertTrue(retry.poll())
        self.assertEqual(launch.call_count, 3)

    def test_active_media_is_never_restarted_by_retry(self):
        now = [100]
        active, launch = Mock(return_value=True), Mock()
        retry = HandoverRetry(active, launch, clock=lambda: now[0])
        retry.arm()
        now[0] = 110
        self.assertFalse(retry.poll())
        launch.assert_not_called()
        active.return_value = False
        now[0] = 120
        self.assertTrue(retry.poll())
        launch.assert_called_once_with()

    def test_hu_reassociation_never_disconnects_or_reselects(self):
        interface=Mock();properties=Mock()
        properties.Get.return_value='/hu-network'
        self.assertTrue(reassociate_target(interface,properties,'/hu-network'))
        interface.Reassociate.assert_called_once_with()
        interface.Disconnect.assert_not_called()
        interface.SelectNetwork.assert_not_called()

    def test_unrelated_home_network_is_not_reassociated(self):
        interface=Mock();properties=Mock()
        properties.Get.return_value='/home-network'
        self.assertFalse(reassociate_target(interface,properties,'/hu-network'))
        interface.assert_not_called()
        interface.Reassociate.assert_not_called()

    def test_ordinary_failures_have_no_grace_period(self):
        self.assertFalse(ReassociationWindow(clock=lambda:100).waiting())

    def test_retired_attempt_can_fail_while_new_association_is_pending(self):
        now=[100]
        retry=ReassociationWindow(clock=lambda:now[0])
        retry.arm()
        self.assertTrue(retry.waiting())
        now[0]=114
        retry.arm()
        self.assertEqual(retry.deadline,115)
        now[0]=115
        self.assertFalse(retry.waiting())

    def test_connected_session_does_not_hide_subsequent_errors(self):
        retry=ReassociationWindow(clock=lambda:100)
        retry.arm();retry.started=True
        self.assertFalse(retry.waiting())

    def test_abandoned_association_requires_two_seconds_without_a_selected_network(self):
        now = [100]
        retry = ReassociationWindow(clock=lambda: now[0])
        retry.arm()
        properties = {'State': 'inactive', 'CurrentNetwork': '/'}
        self.assertFalse(retry.abandoned('idle', properties))
        now[0] = 101
        self.assertFalse(retry.abandoned('idle', properties))
        now[0] = 102
        self.assertTrue(retry.abandoned('idle', properties))

    def test_pending_association_and_unknown_status_keep_the_grace_period(self):
        now = [100]
        retry = ReassociationWindow(clock=lambda: now[0])
        retry.arm()
        idle = {'State': 'inactive', 'CurrentNetwork': '/'}
        self.assertFalse(retry.abandoned('idle', idle))
        for state, properties in (
            ('association', idle),
            ('idle', {'State': 'associating', 'CurrentNetwork': '/'}),
            ('idle', {'State': 'inactive', 'CurrentNetwork': '/hu-network'}),
            ('idle', {}),
        ):
            now[0] += 2
            self.assertFalse(retry.abandoned(state, properties))
            self.assertIsNone(retry.idle_since)
        self.assertFalse(retry.abandoned('idle', idle))

    def test_new_network_and_started_media_cancel_abandoned_detection(self):
        now = [100]
        retry = ReassociationWindow(clock=lambda: now[0])
        retry.arm()
        idle = {'State': 'inactive', 'CurrentNetwork': '/'}
        retry.abandoned('idle', idle)
        now[0] = 102
        retry.arm()
        self.assertFalse(retry.abandoned('idle', idle))
        now[0] = 104
        retry.started = True
        self.assertFalse(retry.abandoned('idle', idle))

    def test_returned_home_connection_confirms_the_hu_attempt_has_ended(self):
        now = [100]
        retry = ReassociationWindow(clock=lambda: now[0])
        retry.arm()
        properties = {'State': 'completed', 'CurrentNetwork': '/home-network'}
        self.assertFalse(retry.abandoned('idle', properties, 'Home', 'HU'))
        now[0] += 2
        self.assertTrue(retry.abandoned('idle', properties, 'Home', 'HU'))

    def test_completed_target_and_unknown_home_identity_are_preserved(self):
        retry = ReassociationWindow(clock=lambda: 100)
        retry.arm()
        for properties, associated, target in (
            ({'State': 'completed', 'CurrentNetwork': '/hu-network'}, 'HU', 'HU'),
            ({'State': 'completed', 'CurrentNetwork': '/home-network'}, None, 'HU'),
            ({'State': 'completed'}, 'Home', 'HU'),
            ({'State': 'associating', 'CurrentNetwork': '/home-network'}, 'Home', 'HU'),
        ):
            with self.subTest(properties=properties, associated=associated):
                self.assertFalse(retry.abandoned('idle', properties, associated, target))
                self.assertIsNone(retry.idle_since)


source_path = Path(__file__).resolve().parents[1] / 'scripts' / 'wifi-session-probe.py'
source_tree = ast.parse(source_path.read_text())
main = next(node for node in source_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
check_callback = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == 'check_wpa2_retry')
factory_tree = ast.parse('''
def callbacks(window):
    wpa2_retry = window
    wpa2_retries = 0
    return check_wpa2_retry, lambda: wpa2_retry
''')
factory_tree.body[0].body.insert(-1, check_callback)
callback_code = compile(factory_tree, str(source_path), 'exec')


class WifiCallbackTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.interface = Mock()
        self.interface.GetAll.return_value = {'State': 'inactive', 'CurrentNetwork': '/'}
        self.service = Mock()
        self.service.GetProperties.return_value = {'State': 'idle', 'Error': 'invalid-key'}
        self.loop, self.connected, self.failed, self.lease = Mock(), Mock(), Mock(), Mock()
        self.namespace = dict(
            service=Mock(return_value=self.service), target='/hu', loop=self.loop,
            connected=self.connected, failed=self.failed, media_lease=self.lease,
            wpa2_interface_path='/fi/w1/wpa_supplicant1/Interfaces/5', bus=Mock(),
            network_object=Mock(), network_interface=Mock(return_value=self.interface),
            ReassociationWindow=lambda: ReassociationWindow(clock=lambda: self.now),
            session={'ssid': 'HU', 'passphrase': 'fixture'}, refresh_session=Mock(),
            args=SimpleNamespace(session='/fixture-session', direct_passphrase=True),
            dbus=SimpleNamespace(DBusException=RuntimeError, String=lambda value, **kwargs: value), print=Mock(),
        )
        exec(callback_code, self.namespace)
        window = self.namespace['ReassociationWindow']()
        window.arm()
        self.check, self.window = self.namespace['callbacks'](window)

    def test_completed_failure_retries_asynchronously_without_releasing_the_lease(self):
        self.assertTrue(self.check())
        self.service.Connect.assert_not_called()
        self.now += 2
        self.assertTrue(self.check())
        self.service.Connect.assert_called_once_with(reply_handler=self.connected, error_handler=self.failed, timeout=12)
        self.loop.quit.assert_not_called()
        self.lease.close.assert_not_called()
        self.assertEqual(self.window().deadline, 0)

    def test_in_worker_retries_stop_after_two_new_attempts(self):
        for attempt in range(3):
            self.window().arm()
            self.assertTrue(self.check())
            self.now += 2
            self.assertEqual(self.check(), attempt < 2)
        self.assertEqual(self.service.Connect.call_count, 2)
        self.loop.quit.assert_called_once_with()

    def test_live_association_keeps_waiting_and_a_ready_network_starts_media(self):
        self.service.GetProperties.return_value = {'State': 'association'}
        self.assertTrue(self.check())
        self.now += 3
        self.assertTrue(self.check())
        self.service.Connect.assert_not_called()
        self.service.GetProperties.return_value = {'State': 'ready'}
        self.assertFalse(self.check())
        self.connected.assert_called_once_with()

    def test_missing_supplicant_snapshot_resets_the_idle_confirmation(self):
        self.assertTrue(self.check())
        self.now += 2
        self.interface.GetAll.side_effect = RuntimeError('retired interface')
        self.assertTrue(self.check())
        self.assertIsNone(self.window().idle_since)
        self.service.Connect.assert_not_called()

    def test_home_connection_retries_in_the_same_worker(self):
        self.interface.GetAll.return_value = {'State': 'completed', 'CurrentNetwork': '/home', 'CurrentBSS': '/home-bss'}
        self.interface.Get.return_value = b'Home'
        self.assertTrue(self.check())
        self.now += 2
        self.assertTrue(self.check())
        self.service.Connect.assert_called_once()
        self.service.SetProperty.assert_called_once_with('Passphrase', 'fixture')
        self.namespace['refresh_session'].assert_called_once_with('/fixture-session', self.namespace['session'])
        self.lease.close.assert_not_called()

    def test_associated_hu_and_bss_read_failures_do_not_trigger_reconnect(self):
        self.interface.GetAll.return_value = {'State': 'completed', 'CurrentNetwork': '/hu', 'CurrentBSS': '/hu-bss'}
        self.interface.Get.return_value = b'HU'
        self.assertTrue(self.check())
        self.now += 2
        self.assertTrue(self.check())
        self.interface.Get.side_effect = RuntimeError('retired BSS')
        self.assertTrue(self.check())
        self.service.Connect.assert_not_called()
        self.assertIsNone(self.window().idle_since)


failure_callback = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == 'failed')
failure_factory = ast.parse('''
def callbacks(window):
    wpa2_retry = window
    wpa2_retries = 0
    wpa2_interface_path = None
    return failed, check_wpa2_retry
''')
failure_factory.body[0].body[-1:-1] = [failure_callback, check_callback]
failure_code = compile(failure_factory, str(source_path), 'exec')


class InitialFailureTests(unittest.TestCase):
    def test_ordinary_failure_arms_bounded_retry_without_retiring_the_worker(self):
        now = [100]
        window = ReassociationWindow(clock=lambda: now[0])
        interface = Mock()
        interface.GetAll.return_value = {'Ifname': 'wlan0', 'State': 'completed', 'CurrentNetwork': '/home', 'CurrentBSS': '/home-bss'}
        interface.Get.return_value = b'Home'
        root = Mock()
        root.Get.return_value = ['/wifi-interface']
        service = Mock()
        service.GetProperties.return_value = {'Type': 'wifi', 'Name': 'HU', 'Ethernet': {'Interface': 'wlan0'}, 'State': 'idle'}
        loop, connected = Mock(), Mock()
        namespace = dict(
            service=Mock(return_value=service), target='/hu', loop=loop, connected=connected,
            bus=Mock(), network_object=lambda bus, name, path: path,
            network_interface=lambda path, name: root if path == '/fi/w1/wpa_supplicant1' else interface,
            session={'ssid': 'HU', 'addresses': [], 'port': 7000, 'passphrase': 'fixture'},
            args=SimpleNamespace(session='/fixture', direct_passphrase=False), refresh_session=Mock(),
            dbus=SimpleNamespace(DBusException=RuntimeError), print=Mock(),
            ReassociationWindow=lambda: ReassociationWindow(clock=lambda: now[0]),
        )
        exec(failure_code, namespace)
        failed, check = namespace['callbacks'](window)
        failed(SimpleNamespace(get_dbus_name=lambda: 'net.connman.Error.Failed'))
        self.assertEqual(window.deadline, 115)
        loop.quit.assert_not_called()
        self.assertTrue(check())
        now[0] += 2
        self.assertTrue(check())
        service.Connect.assert_called_once_with(reply_handler=connected, error_handler=failed, timeout=12)
        service.SetProperty.assert_not_called()
