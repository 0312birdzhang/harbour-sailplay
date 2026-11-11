"""Regressions for switching receivers and app-owned SDP services started after pairing."""
import errno
import struct
import threading
import unittest
from unittest.mock import Mock, patch

from android_auto.bluez import AA_UUID, CARPLAY_UUID, select_head_unit
from android_auto.bluetooth import BTPROTO_RFCOMM, connect_bluetooth, discover_head_units, find_channel, rfcomm_channel


ADAPTER = '/org/bluez/hci1'
PIXEL = ADAPTER + '/dev_3C_28_6D_2C_FC_2E'
OLD = ADAPTER + '/dev_EC_A7_AD_81_EA_86'
ATTRIBUTES = bytes.fromhex('354d36004a0900000a0001000f09000135111c4de17a0052cb11e6bdf40800200c9a66'
                           '090004350c3503190100350519000308090900053503191002090100250e4141204254204c697374656e6572')


def devices():
    return {
        ADAPTER: {'org.bluez.Adapter1': {'Powered': True, 'Address': '50:56:A8:06:01:73'}},
        OLD: {'org.bluez.Device1': {'Paired': True, 'Connected': False, 'UUIDs': [CARPLAY_UUID]}},
        PIXEL: {'org.bluez.Device1': {'Paired': True, 'Connected': True,
                                    'Address': '3C:28:6D:2C:FC:2E', 'UUIDs': []}},
    }


class ReceiverSelectionTests(unittest.TestCase):
    def test_live_sdp_overrides_disconnected_packaged_vehicle_without_mutating_bluez(self):
        objects = devices()
        with patch('android_auto.bluetooth.find_channel', return_value=9):
            current, channels = discover_head_units(objects, ADAPTER)
        self.assertEqual(select_head_unit(current, OLD, protocol='android-auto'), PIXEL)
        self.assertEqual(channels, {PIXEL: 9})
        self.assertEqual(objects[PIXEL]['org.bluez.Device1']['UUIDs'], [])

    def test_non_receivers_are_rejected_and_unpaired_devices_are_not_probed(self):
        objects = devices()
        with patch('android_auto.bluetooth.find_channel', return_value=None) as probe:
            current, channels = discover_head_units(objects, ADAPTER)
        self.assertIsNone(select_head_unit(current, protocol='android-auto'))
        self.assertEqual(channels, {})
        probe.assert_called_once()
        objects[PIXEL]['org.bluez.Device1']['Paired'] = False
        with patch('android_auto.bluetooth.find_channel') as probe:
            discover_head_units(objects, ADAPTER)
        probe.assert_not_called()

    def test_saved_device_is_resolved_after_adapter_renumbering(self):
        objects = devices()
        objects[PIXEL]['org.bluez.Device1']['Connected'] = False
        self.assertEqual(select_head_unit(objects, previous=PIXEL.replace('hci1', 'hci0'),
                                         protocol='android-auto'), PIXEL)

    def test_stop_prevents_new_sdp_queries(self):
        stop = threading.Event()
        stop.set()
        with patch('android_auto.bluetooth.find_channel') as probe:
            discover_head_units(devices(), ADAPTER, stop)
        probe.assert_not_called()

    def test_disconnected_verified_receiver_can_wake_without_probing_other_paired_devices(self):
        for advertised in ([], [AA_UUID]):
            with self.subTest(advertised=advertised):
                objects = devices()
                properties = objects[PIXEL]['org.bluez.Device1']
                properties.update(Connected=False, UUIDs=advertised)
                with patch('android_auto.bluetooth.find_channel', return_value=8) as probe:
                    current, channels = discover_head_units(objects, ADAPTER, known_device=PIXEL.replace('hci1', 'hci0'))
                probe.assert_called_once()
                self.assertEqual(channels, {PIXEL: 8})
                self.assertEqual(current[PIXEL]['org.bluez.Device1']['UUIDs'], [AA_UUID])
                self.assertEqual(select_head_unit(current, previous=PIXEL, protocol='android-auto'), PIXEL)

    def test_multiple_discovered_receivers_require_a_known_identity(self):
        objects = devices()
        properties = dict(objects[PIXEL]['org.bluez.Device1'], UUIDs=[AA_UUID])
        objects[PIXEL]['org.bluez.Device1'] = properties
        objects[ADAPTER + '/dev_00_11_22_33_44_55'] = {'org.bluez.Device1': dict(properties)}
        with self.assertRaises(RuntimeError):
            select_head_unit(objects, protocol='android-auto')
        self.assertEqual(select_head_unit(objects, previous=PIXEL, protocol='android-auto'), PIXEL)


class SdpTests(unittest.TestCase):
    def test_interrupted_connect_waits_for_completion(self):
        peer = Mock()
        peer.getsockopt.return_value = 0
        libc = Mock()
        libc.bind.return_value = 0
        libc.connect.return_value = -1
        with patch('android_auto.bluetooth.socket.socket', return_value=peer), \
                patch('android_auto.bluetooth.ctypes.CDLL', return_value=libc), \
                patch('android_auto.bluetooth.ctypes.get_errno', return_value=errno.EINTR), \
                patch('android_auto.bluetooth.select.select', return_value=([], [peer], [])):
            self.assertIs(connect_bluetooth('50:56:A8:06:01:73', '3C:28:6D:2C:FC:2E', 9, BTPROTO_RFCOMM), peer)
        peer.close.assert_not_called()

    def test_real_dauto_service_reports_rfcomm_channel_nine(self):
        self.assertEqual(rfcomm_channel(ATTRIBUTES), 9)
        self.assertIsNone(rfcomm_channel(b'\x35\x00'))

    def test_truncated_and_non_android_auto_records_are_rejected(self):
        for end in range(1, len(ATTRIBUTES)):
            with self.subTest(end=end), self.assertRaises(ValueError):
                rfcomm_channel(ATTRIBUTES[:end])
        self.assertIsNone(rfcomm_channel(ATTRIBUTES.replace(bytes.fromhex(AA_UUID.replace('-', '')), bytes(16))))

    def test_continuation_reassembles_service_attributes(self):
        def response(transaction, data, state):
            payload = struct.pack('!H', len(data)) + data + state
            return struct.pack('!BHH', 7, transaction, len(payload)) + payload
        peer = Mock()
        peer.recv.side_effect = [response(1, ATTRIBUTES[:35], b'\x01\x42'),
                                 response(2, ATTRIBUTES[35:], b'\x00')]
        peer.__enter__ = Mock(return_value=peer)
        peer.__exit__ = Mock()
        with patch('android_auto.bluetooth.connect_bluetooth', return_value=peer):
            self.assertEqual(find_channel('50:56:A8:06:01:73', '3C:28:6D:2C:FC:2E'), 9)
        self.assertTrue(peer.sendall.call_args[0][0].endswith(b'\x01\x42'))


if __name__ == '__main__':
    unittest.main()
