import unittest
from unittest.mock import Mock
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
