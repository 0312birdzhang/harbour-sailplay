import unittest
from unittest.mock import Mock
from carplay_proto.wifidiscovery import discover


class DiscoveryTests(unittest.TestCase):
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

    def test_stale_service_list_cycles_wifi_only_once(self):
        manager = Mock()
        manager.GetServices.return_value = []
        result, power = self.run_discovery(manager, Mock(return_value=True))
        self.assertIsNone(result[0])
        self.assertEqual([c.args for c in power.call_args_list], [('/wifi', False), ('/wifi', True)])
