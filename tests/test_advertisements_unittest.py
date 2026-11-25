import importlib.util
from pathlib import Path
import unittest
import uuid

spec = importlib.util.spec_from_file_location('phone_advertise',
    Path(__file__).resolve().parents[1] / 'scripts' / 'wireless-phone-advertise.py')
advertise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(advertise)


class AdvertisementTests(unittest.TestCase):
    def test_existing_carplay_marker_still_requires_iap2(self):
        self.assertEqual(advertise.missing_advertisements([advertise.PHONE_EIR]),
                         [advertise.IAP_V2_EIR])

    def test_preserves_existing_services_case_insensitively(self):
        existing = [advertise.PHONE_EIR.upper(), advertise.IAP_V2_EIR.upper(), 'other']
        self.assertEqual(advertise.missing_advertisements(existing), [])
        self.assertEqual(len(existing), 3)

    def test_both_required_when_absent(self):
        self.assertEqual(advertise.missing_advertisements([]),
                         [advertise.PHONE_EIR, advertise.IAP_V2_EIR])


class FakeControl:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class LifecycleTests(unittest.TestCase):
    """What the adapter advertises after bluetoothd was replaced."""
    def setUp(self):
        self.adapter_uuids = []
        self.sent = []
        self.control = None

        def open_control():
            self.control = FakeControl()
            return self.control

        def send(sock, opcode, payload, adapter_index):
            value = str(uuid.UUID(bytes=bytes(payload[:16][::-1])))
            self.sent.append((opcode, value, adapter_index))
            if opcode == 0x0010:
                self.adapter_uuids.append(value)
            elif value in self.adapter_uuids:
                self.adapter_uuids.remove(value)

        self.advertisement = advertise.Advertisement(
            lambda: ('/org/bluez/hci1', 1, list(self.adapter_uuids)), open_control, send)

    def bluetoothd_restarts(self):
        # A new bluetoothd clears the adapter's service UUIDs.
        self.adapter_uuids.clear()

    def run_rounds(self, results, after_launch=lambda count: None):
        launches = []

        def launch(arguments):
            launches.append(arguments)
            after_launch(len(launches))
            return results[len(launches) - 1]

        advertise.run_probe('probe.py', ensure=self.advertisement.ensure, launch=launch,
                            sleep=lambda seconds: None, rounds=len(results))
        return launches

    def test_markers_present_at_startup_are_restored_when_the_probe_exits_after_a_restart(self):
        self.adapter_uuids += [advertise.PHONE_EIR, advertise.IAP_V2_EIR]
        launches = self.run_rounds([0, 0], after_launch=lambda count: count == 1 and self.bluetoothd_restarts())
        self.assertEqual(len(launches), 2)
        self.assertEqual(advertise.missing_advertisements(self.adapter_uuids), [])
        self.assertEqual([entry[:2] for entry in self.sent],
                         [(0x0010, advertise.PHONE_EIR), (0x0010, advertise.IAP_V2_EIR)])
        self.assertTrue(all(entry[2] == 1 for entry in self.sent))

    def test_markers_that_survive_a_probe_exit_are_not_added_again(self):
        self.adapter_uuids += [advertise.PHONE_EIR, advertise.IAP_V2_EIR]
        self.run_rounds([0, 1, 0])
        self.assertEqual(self.sent, [])
        self.assertIsNone(self.control)

    def test_markers_added_at_startup_are_added_once_and_removed_on_exit(self):
        self.assertEqual(self.advertisement.ensure(), [advertise.PHONE_EIR, advertise.IAP_V2_EIR])
        self.assertEqual(self.advertisement.ensure(), [])
        self.advertisement.close()
        self.assertEqual(self.adapter_uuids, [])
        self.assertEqual([entry[0] for entry in self.sent], [0x0010, 0x0010, 0x0011, 0x0011])
        self.assertTrue(self.control.closed)

    def test_markers_restored_after_a_restart_are_removed_on_exit_too(self):
        self.adapter_uuids += [advertise.PHONE_EIR, advertise.IAP_V2_EIR]
        self.run_rounds([0], after_launch=lambda count: self.bluetoothd_restarts())
        self.advertisement.close()
        self.assertEqual(self.adapter_uuids, [])

    def test_a_check_that_fails_while_bluetoothd_starts_does_not_stop_the_relaunch(self):
        def unavailable():
            raise OSError('org.bluez is not there yet')
        launches = []
        advertise.run_probe('probe.py', ensure=unavailable, launch=lambda arguments: launches.append(1) or 0,
                            sleep=lambda seconds: None, rounds=3)
        self.assertEqual(len(launches), 3)
