import unittest
from unittest.mock import Mock, patch

from carplay_proto.mobiledata import MobileDataKeeper, RETRY_SECONDS


CELL = '/net/connman/service/cellular_1_context1'
WIFI = '/net/connman/service/wifi_hu_managed_psk'


class ConnmanError(Exception):
    def __init__(self, name):
        self.name = name

    def get_dbus_name(self):
        return self.name


class MobileDataTests(unittest.TestCase):
    def setUp(self):
        self.keeper = MobileDataKeeper(log=Mock())
        self.keeper.system, self.keeper.manager = Mock(), Mock()
        self.cell = {'Type': 'cellular', 'State': 'online', 'AutoConnect': True}
        self.wifi = {'Type': 'wifi', 'State': 'ready', 'AutoConnect': True}
        self.keeper.manager.GetServices.side_effect = lambda: [(WIFI, self.wifi), (CELL, self.cell)]
        self.service = Mock()
        self.now = 500
        patches = [patch('carplay_proto.mobiledata.network_object', return_value=self.service),
                   patch('carplay_proto.mobiledata.network_interface', side_effect=lambda obj, name: obj),
                   patch('carplay_proto.mobiledata.time.monotonic', side_effect=lambda: self.now)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def logged(self):
        return [call.args[0] for call in self.keeper.log.call_args_list]

    def test_connected_mobile_data_and_wifi_are_left_alone(self):
        self.keeper.poll()
        self.wifi['State'] = 'idle'
        self.keeper.poll()
        self.service.Connect.assert_not_called()

    def test_mobile_data_dropped_during_the_projection_is_requested_again(self):
        self.keeper.poll()
        self.cell['State'] = 'idle'
        self.keeper.poll()
        self.service.Connect.assert_called_once_with(timeout=RETRY_SECONDS)
        self.keeper.poll()
        self.service.Connect.assert_called_once()
        self.now += RETRY_SECONDS
        self.keeper.poll()
        self.assertEqual(self.service.Connect.call_count, 2)
        self.cell['State'] = 'ready'
        self.keeper.poll()
        self.assertIn('Mobile data restored service={} state=ready'.format(CELL), self.logged())
        self.now += RETRY_SECONDS
        self.keeper.poll()
        self.assertEqual(self.service.Connect.call_count, 2)

    def test_mobile_data_that_was_never_up_is_not_connected(self):
        self.cell['State'] = 'idle'
        self.keeper.poll()
        self.service.Connect.assert_not_called()

    def test_mobile_data_switched_off_by_the_user_stays_off(self):
        self.keeper.poll()
        self.cell.update(State='idle', AutoConnect=False)
        self.keeper.poll()
        self.cell['AutoConnect'] = True
        self.now += RETRY_SECONDS
        self.keeper.poll()
        self.service.Connect.assert_not_called()

    def test_a_connection_in_progress_is_not_interrupted_and_errors_are_reported(self):
        self.keeper.poll()
        self.cell['State'] = 'association'
        self.keeper.poll()
        self.service.Connect.assert_not_called()
        self.cell['State'] = 'failure'
        self.service.Connect.side_effect = ConnmanError('net.connman.Error.PermissionDenied')
        self.keeper.poll()
        self.assertIn('Mobile data reconnection service={} error=net.connman.Error.PermissionDenied'.format(CELL),
                      self.logged())


if __name__ == '__main__':
    unittest.main()
