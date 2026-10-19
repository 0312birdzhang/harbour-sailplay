import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from carplay_proto.networkrecovery import recover_split_registry


class RegistryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / 'recovery.json')
        self.live = dict(Type='wifi', Name='HU', State='idle', Ethernet={'Interface': 'wlan0'})
        self.detached = dict(Type='wifi', Name='HU', State='idle', Ethernet={})
        self.manager = Mock()
        self.manager.GetServices.return_value = [('/hu', self.live)]
        self.service = Mock()
        self.service.return_value.GetProperties.return_value = self.detached
        self.restart = Mock()

    def recover(self, owner='owner1', now=1000):
        return recover_split_registry(self.manager, self.service, '/hu', 'HU', owner,
            log=Mock(), state_path=self.path, restart=self.restart, clock=lambda: now)

    def test_confirmed_split_restarts_once_across_workers(self):
        self.assertTrue(self.recover())
        self.assertFalse(self.recover(now=2000))
        self.restart.assert_called_once()

    def test_new_owner_is_rate_limited_but_can_recover_later(self):
        self.assertTrue(self.recover())
        self.assertFalse(self.recover('owner2', 1100))
        self.assertTrue(self.recover('owner2', 1400))
        self.assertEqual(self.restart.call_count, 2)

    def test_ordinary_no_carrier_does_not_restart(self):
        self.service.return_value.GetProperties.return_value = self.live
        self.assertFalse(self.recover())
        self.manager.GetServices.return_value = [('/hu', self.detached)]
        self.service.return_value.GetProperties.return_value = self.detached
        self.assertFalse(self.recover())
        self.restart.assert_not_called()

    def test_one_snapshot_race_does_not_restart(self):
        self.service.return_value.GetProperties.side_effect = [self.detached, self.live]
        self.assertFalse(self.recover())
        self.restart.assert_not_called()

    def test_active_session_or_other_target_is_never_restarted(self):
        for change in (dict(State='ready'), dict(State='association'), dict(Name='other')):
            self.service.return_value.GetProperties.return_value = dict(self.detached, **change)
            self.assertFalse(self.recover())
        self.restart.assert_not_called()


if __name__ == '__main__':
    unittest.main()
