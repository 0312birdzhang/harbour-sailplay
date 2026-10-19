import unittest
from unittest.mock import Mock, patch
from carplay_proto.projectionpower import CpuLease, ProjectionPower, ProfileConnectionPower


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


class BoundedPowerTests(unittest.TestCase):
    def test_profile_retries_cannot_extend_one_bluetooth_wake_window(self):
        factory = Mock()
        window = ProfileConnectionPower(factory)
        window.open()
        window.open()
        window.open()
        factory.assert_called_once_with()
        factory.return_value.start.assert_called_once_with()
        window.close()
        window.close()
        factory.return_value.close.assert_called_once_with()

    def test_new_link_can_open_a_fresh_profile_wake_window(self):
        factory = Mock(side_effect=[Mock(), Mock()])
        window = ProfileConnectionPower(factory)
        window.open()
        previous = window.power
        window.close()
        window.open()
        self.assertIsNot(window.power, previous)
        window.close()

    def test_connection_deadline_releases_without_waking_display(self):
        now = [0.0]
        api = Mock()
        api.req_cpu_keepalive_period.return_value = 60
        api.req_cpu_keepalive_start.return_value = True
        module = Mock()
        module.Interface.return_value = api
        power = ProjectionPower(phase='connection', maximum_seconds=90,
                                clock=lambda: now[0])
        power.stop = Mock()
        power.stop.is_set.return_value = False
        power.stop.wait.side_effect = lambda delay: now.__setitem__(0, now[0] + delay)
        with patch.dict('sys.modules', dbus=module), patch('builtins.print'):
            power.run()
        self.assertEqual(now[0], 90)
        api.req_cpu_keepalive_start.assert_called()
        api.req_cpu_keepalive_stop.assert_called_once_with(power.token, timeout=2)
        module.SystemBus.return_value.close.assert_called_once()
        api.req_display_state_on.assert_not_called()
        api.req_tklock_mode_change.assert_not_called()

    def test_overlapping_setup_and_media_have_independent_tokens(self):
        setup = ProjectionPower(phase='connection', maximum_seconds=90)
        media = ProjectionPower()
        another_setup = ProjectionPower(phase='connection', maximum_seconds=90)
        self.assertEqual(len({setup.token, media.token, another_setup.token}), 3)

    def test_out_of_range_connection_deadline_is_rejected(self):
        for seconds in (0, -1, 121):
            with self.assertRaises(ValueError):
                ProjectionPower(phase='connection', maximum_seconds=seconds)
