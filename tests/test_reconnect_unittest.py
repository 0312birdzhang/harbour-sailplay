import importlib.util
import errno
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('reconnect_car',
    Path(__file__).resolve().parents[1] / 'scripts' / 'reconnect-car.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConfiguredHeadUnitTests(unittest.TestCase):
    def test_busy_sdp_connection_retries_with_a_fresh_socket(self):
        with patch('android_auto.bluetooth.find_channel', side_effect=[OSError(errno.EALREADY, 'busy'), 9]) as sdp, \
                patch.object(module.time, 'sleep') as sleep:
            self.assertEqual(module.wake_android_auto('local', 'remote'), 9)
        self.assertEqual(sdp.call_count, 2)
        sleep.assert_called_once_with(.5)
        self.assertTrue(all(call.kwargs['timeout'] == 10 for call in sdp.call_args_list))

    def test_sdp_retries_are_bounded_and_preserve_terminal_errors(self):
        for number, count in ((errno.EINPROGRESS, 3), (errno.EALREADY, 3), (errno.EACCES, 1)):
            error = OSError(number, 'Bluetooth connection failed')
            with self.subTest(number=number), \
                    patch('android_auto.bluetooth.find_channel', side_effect=error) as sdp, \
                    patch.object(module.time, 'sleep') as sleep, self.assertRaises(OSError) as raised:
                module.wake_android_auto('local', 'remote')
            self.assertIs(raised.exception, error)
            self.assertEqual(sdp.call_count, count)
            self.assertEqual(sleep.call_count, count - 1)

    def test_extracts_device_from_systemd_execstart(self):
        target = '/org/bluez/hci1/dev_EC_A7_AD_81_EA_86'
        self.assertEqual(module.configured_device(
            'ExecStart={ path=/usr/bin/python3 ; argv[]=python3 probe --device ' + target + ' --sustained ; }'), target)

    def test_service_without_target_uses_discovery(self):
        self.assertIsNone(module.configured_device('ExecStart=python3 probe --seconds 0'))

    def test_packaged_service_has_no_vehicle_address(self):
        service = Path(__file__).resolve().parents[1] / 'rpm' / 'sailplay.service'
        self.assertNotIn('--device', service.read_text())

    def test_reconnect_wakes_android_auto_and_preserves_connected_carplay_profiles(self):
        target = '/org/bluez/hci1/dev_3C_28_6D_2C_FC_2E'
        adapter = '/org/bluez/hci1'
        for protocol, connected in (('android-auto', True), ('android-auto', False),
                                    ('auto', True), ('carplay', True), ('carplay', False)):
            with self.subTest(protocol=protocol, connected=connected):
                manager, properties, device = Mock(), Mock(), Mock()
                manager.GetManagedObjects.return_value = {}
                properties.Get.return_value = connected
                interfaces = {'org.freedesktop.DBus.ObjectManager': manager,
                              'org.freedesktop.DBus.Properties': properties,
                              'org.bluez.Device1': device, 'net.connman.Manager': manager}
                dbus = SimpleNamespace(SystemBus=Mock(), Boolean=bool, DBusException=RuntimeError,
                    Interface=lambda obj, name: interfaces[name])
                with patch.dict('sys.modules', {'dbus': dbus}), \
                        patch.object(module.subprocess, 'check_output', return_value='ExecStart=projection-service.py'), \
                        patch.object(module.subprocess, 'run'), \
                        patch.object(module, 'select_adapter', return_value=(adapter, target)), \
                        patch.object(module, 'selected_protocol', return_value=protocol), \
                        patch.object(module, 'projection_target', return_value=target), \
                        patch.object(module, 'authenticated_head_unit', return_value=False), \
                        patch.object(module, 'remember_head_unit'), \
                        patch('android_auto.bluez.select_head_unit', return_value=target), \
                        patch('android_auto.bluetooth.find_channel') as sdp, \
                        patch('android_auto.bluetooth.discover_head_units', return_value=({}, {})), \
                        patch('carplay_proto.wifidiscovery.ensure_wifi_powered'):
                    module.main()
                if protocol != 'carplay':
                    device.Connect.assert_not_called()
                    sdp.assert_called_once()
                    self.assertEqual(sdp.call_args.kwargs['timeout'], 10)
                    if connected:
                        device.Disconnect.assert_called_once_with(timeout=10)
                    else:
                        device.Disconnect.assert_not_called()
                elif connected:
                    device.Connect.assert_not_called()
                    device.Disconnect.assert_not_called()
                    sdp.assert_not_called()
                else:
                    device.Connect.assert_called_once_with(timeout=20)
