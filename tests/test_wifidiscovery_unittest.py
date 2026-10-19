import unittest
from unittest.mock import Mock
from carplay_proto.wifidiscovery import discover, find_service, ensure_wifi_powered


class DiscoveryTests(unittest.TestCase):
    def test_saved_hotspot_without_signal_is_not_available(self):
        saved=[('/hu',{'Type':'wifi','Name':'HU','State':'idle','Favorite':True})]
        self.assertEqual(find_service(saved,'HU'),'/hu')
        self.assertIsNone(find_service(saved,'HU',require_available=True))
        saved[0][1]['Strength']=72
        self.assertEqual(find_service(saved,'HU',require_available=True),'/hu')

    def test_connected_hotspot_can_be_reused_without_strength(self):
        self.assertEqual(find_service([('/hu',{'Type':'wifi','Name':'HU','State':'ready'})],
                                     'HU',require_available=True),'/hu')

    def test_stale_profile_is_scanned_until_signal_appears(self):
        manager=Mock()
        manager.GetServices.side_effect=[
            [('/hu',{'Type':'wifi','Name':'HU','State':'idle'})],
            [('/hu',{'Type':'wifi','Name':'HU','State':'idle','Strength':72})]]
        scan=Mock();power=Mock()
        result=discover(manager,'/wifi','HU',scan,Mock(return_value=False),power,
                        require_available=True)
        self.assertEqual(result[0],'/hu')
        scan.assert_called_once_with('/wifi')
        power.assert_not_called()

    def run_discovery(self, manager, visible):
        now = [0]
        power = Mock()
        def sleep(seconds): now[0] += seconds
        result = discover(manager, '/wifi', 'HU', Mock(), visible, power,
                          log=Mock(), clock=lambda: now[0], sleep=sleep, timeout=10)
        return result, power

    def test_existing_service_does_not_change_wifi(self):
        manager = Mock()
        manager.GetServices.return_value = [('/hu', {'Type': 'wifi', 'Name': 'HU'})]
        result, power = self.run_discovery(manager, Mock(return_value=True))
        self.assertEqual(result[0], '/hu')
        power.assert_not_called()

    def test_absent_bss_does_not_cycle_wifi(self):
        manager = Mock()
        manager.GetServices.return_value = []
        result, power = self.run_discovery(manager, Mock(return_value=False))
        self.assertIsNone(result[0])
        power.assert_not_called()

    def test_stale_service_list_never_turns_wifi_off(self):
        manager = Mock()
        manager.GetServices.return_value = []
        result, power = self.run_discovery(manager, Mock(return_value=True))
        self.assertIsNone(result[0])
        power.assert_not_called()

    def test_carplay_enables_disabled_wifi_without_disabling_it(self):
        manager = Mock()
        manager.GetTechnologies.return_value = [('/wifi', {'Type':'wifi','Powered':False})]
        power = Mock()
        self.assertEqual(ensure_wifi_powered(manager,power,log=Mock()), '/wifi')
        power.assert_called_once_with('/wifi',True)

    def test_enabled_wifi_and_current_connection_are_untouched(self):
        manager = Mock()
        manager.GetTechnologies.return_value = [('/wifi', {'Type':'wifi','Powered':True})]
        power = Mock()
        ensure_wifi_powered(manager,power)
        power.assert_not_called()
        manager.GetServices.assert_not_called()


class RestartError(Exception):
    def get_dbus_name(self):
        return 'org.freedesktop.DBus.Error.ServiceUnknown'


class RestartDiscoveryTests(unittest.TestCase):
    def test_daemon_replacement_during_discovery_recovers_in_same_worker(self):
        manager=Mock()
        manager.GetServices.side_effect=[RestartError(), [('/new',{'Type':'wifi','Name':'HU','State':'ready'})]]
        log=Mock()
        target,_=discover(manager,'/wifi','HU',Mock(),Mock(),Mock(),log=log)
        self.assertEqual(target,'/new')
        self.assertTrue(any('waiting for ConnMan' in call.args[0] for call in log.call_args_list))

    def test_absent_daemon_does_not_escape_discovery_deadline(self):
        manager=Mock();manager.GetServices.side_effect=RestartError()
        now=[0]
        def scan(path): now[0]+=2
        def sleep(seconds): now[0]+=seconds
        target,_=discover(manager,'/wifi','HU',scan,Mock(),Mock(),log=Mock(),clock=lambda:now[0],sleep=sleep,timeout=6)
        self.assertIsNone(target)
        self.assertLessEqual(now[0],6)
