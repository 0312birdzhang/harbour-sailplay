import unittest
from unittest.mock import Mock, patch
from carplay_proto.wifidiscovery import verify_local_carplay

class LocalCarplayTests(unittest.TestCase):
    def setUp(self):
        self.props={'Type':'wifi','Name':'HU','State':'ready','Ethernet':{'Interface':'wlan0'}}
        self.probe=Mock(return_value='192.168.43.155')
    def check(self,associated='HU',addresses=None):
        return verify_local_carplay(self.props,'HU',associated,addresses or ['192.168.43.2'],7000,self.probe,log=lambda _:None)
    def test_ready_without_dns_or_internet_is_enough(self):
        self.assertTrue(self.check());self.probe.assert_called_once_with('192.168.43.2',7000,'wlan0')
    def test_inconsistent_connman_idle_can_continue_if_actual_link_works(self):
        self.props['State']='idle';self.assertTrue(self.check())
    def test_stale_ip_on_other_wifi_cannot_bypass(self):
        self.props['IPv4']={'Address':'192.168.43.155'}
        self.assertFalse(self.check('Home'));self.probe.assert_not_called()
    def test_missing_association_cannot_bypass(self):
        self.assertFalse(self.check(None));self.probe.assert_not_called()
    def test_tcp_failure_keeps_recovery(self):
        self.probe.side_effect=OSError('unreachable');self.assertFalse(self.check())
    def test_ipv6_link_local_without_ipv4_works(self):
        self.probe.return_value='fe80::1234';self.assertTrue(self.check(addresses=['fe80::abcd']))
    def test_loopback_and_hostnames_are_not_probed(self):
        self.assertFalse(self.check(addresses=['localhost','127.0.0.1','::','ff02::1']));self.probe.assert_not_called()
    def test_unspecified_source_is_not_proof(self):
        self.probe.return_value='0.0.0.0';self.assertFalse(self.check())

    def test_missing_gateway_uses_the_first_host_on_the_confirmed_hu_wifi(self):
        self.props['State'] = 'configuration'
        self.props['IPv4'] = {'Address': '192.168.50.102', 'Netmask': '255.255.255.0'}
        self.probe.return_value = '192.168.50.102'
        with patch('carplay_proto.airplaydiscovery.discover') as discover:
            self.assertTrue(verify_local_carplay(self.props, 'HU', 'HU', [], 7000, self.probe,
                                               log=Mock()))
        self.probe.assert_called_once_with('192.168.50.1', 7000, 'wlan0')
        discover.assert_not_called()

    def test_missing_gateway_uses_discovered_endpoint_when_the_first_host_is_silent(self):
        self.props['State'] = 'configuration'
        self.props['IPv4'] = {'Address': '192.168.50.102', 'Netmask': '255.255.255.0'}
        self.probe.side_effect = [OSError('unreachable'), '192.168.50.102']
        with patch('carplay_proto.airplaydiscovery.discover', return_value=[('192.168.50.2', 12345)]), \
                patch('carplay_proto.airplaydiscovery.interface_address', return_value='192.168.50.102'):
            self.assertTrue(verify_local_carplay(self.props, 'HU', 'HU', [], 7000, self.probe,
                                               log=Mock()))
        self.assertEqual([call.args for call in self.probe.call_args_list],
                         [('192.168.50.1', 7000, 'wlan0'), ('192.168.50.2', 12345, 'wlan0')])

    def test_discovery_cannot_bypass_unconfirmed_association(self):
        with patch('carplay_proto.airplaydiscovery.discover') as discover:
            self.assertFalse(verify_local_carplay(self.props, 'HU', 'Home', [], 7000, self.probe,
                                                log=Mock()))
        discover.assert_not_called()
        self.probe.assert_not_called()
