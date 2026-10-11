import unittest
from unittest.mock import Mock
from carplay_proto.projectionpower import CpuLease


class CpuLeaseTests(unittest.TestCase):
    def test_renews_before_expiry_and_releases_same_token(self):
        api = Mock()
        api.req_cpu_keepalive_period.return_value = 60
        api.req_cpu_keepalive_start.return_value = True
        lease = CpuLease(api, 'projection')
        self.assertEqual(lease.renew(), 20)
        lease.close()
        api.req_cpu_keepalive_stop.assert_called_once_with('projection', timeout=2)
        api.req_display_state_on.assert_not_called()
        api.req_tklock_mode_change.assert_not_called()

    def test_short_lease_is_refreshed_early_and_rejection_detected(self):
        api = Mock()
        api.req_cpu_keepalive_period.return_value = 9
        api.req_cpu_keepalive_start.return_value = True
        lease = CpuLease(api, 'projection')
        self.assertEqual(lease.renew(), 3)
        api.req_cpu_keepalive_start.return_value = False
        with self.assertRaises(RuntimeError):
            lease.renew()
