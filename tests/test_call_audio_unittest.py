import unittest
from unittest.mock import Mock, patch

from carplay_proto.callaudio import BLUETOOTH_OVERRIDE, CallAudioRouter, HFP_HEADSET, VOICE_MANAGER


class BluezError(Exception):
    def __init__(self, name):
        self.name = name

    def get_dbus_name(self):
        return self.name


class CallAudioTests(unittest.TestCase):
    def setUp(self):
        self.router = CallAudioRouter('/org/bluez/hci1/dev_HU', log=Mock())
        self.router.system, self.router.voice, self.router.routes, self.router.devices = [Mock() for _ in range(4)]
        self.router.system.get_name_owner.return_value = ':1.5'
        self.properties = {'voiceCalls': ['/call/1'], 'isAudioRouted': True, 'audioMode': 'earpiece'}
        self.router.voice.GetAll.side_effect = lambda name: self.properties
        self.target_properties = {'Paired': True, 'Connected': False, 'UUIDs': [HFP_HEADSET]}
        self.objects = {'/org/bluez/hci1/dev_HU': {'org.bluez.Device1': self.target_properties}}
        self.router.devices.GetManagedObjects.side_effect = lambda: self.objects
        self.features = [(BLUETOOTH_OVERRIDE, 1, 1)]
        self.router.routes.GetAll.side_effect = lambda: ('earpiece', 1, 'microphone', 2, self.features)
        self.device = Mock()
        self.device.ConnectProfile.side_effect = lambda *args, **kwargs: self.target_properties.update(Connected=True)
        self.object_patch = patch('carplay_proto.callaudio.network_object', return_value=self.device)
        self.interface_patch = patch('carplay_proto.callaudio.network_interface', side_effect=lambda obj, name: obj)
        self.now = 1000
        self.clock_patch = patch('carplay_proto.callaudio.time.monotonic', side_effect=lambda: self.now)
        self.object_patch.start()
        self.interface_patch.start()
        self.clock_patch.start()
        self.addCleanup(self.object_patch.stop)
        self.addCleanup(self.interface_patch.stop)
        self.addCleanup(self.clock_patch.stop)

    def poll(self):
        self.router.poll()
        self.router.voice.GetAll.assert_called_with(VOICE_MANAGER)

    def test_idle_projection_leaves_bluetooth_and_audio_routes_alone(self):
        self.properties['voiceCalls'] = []
        self.poll()
        self.device.ConnectProfile.assert_not_called()
        self.router.routes.GetAll.assert_not_called()
        self.router.routes.Enable.assert_not_called()
        self.router.routes.Disable.assert_not_called()

    def test_standby_connects_hfp_before_any_call_and_keeps_it_between_calls(self):
        self.router.keep_connected = True
        self.target_properties['Connected'] = True
        self.properties['voiceCalls'] = []
        self.poll()
        self.device.ConnectProfile.assert_called_once_with(HFP_HEADSET, timeout=6)
        self.assertEqual(self.router.standby_device, '/org/bluez/hci1/dev_HU')
        self.now += 60
        self.poll()
        self.device.ConnectProfile.assert_called_once()
        self.properties['voiceCalls'] = ['/call/1']
        self.device.ConnectProfile.side_effect = BluezError('org.bluez.Error.AlreadyConnected')
        self.poll()
        self.properties['voiceCalls'] = []
        self.poll()
        self.device.DisconnectProfile.assert_not_called()
        self.assertTrue(self.router.release(final=True))
        self.device.DisconnectProfile.assert_called_once_with(HFP_HEADSET, timeout=5)

    def test_standby_waits_for_the_head_unit_and_reconnects_after_a_drop(self):
        self.router.keep_connected = True
        self.properties['voiceCalls'] = []
        self.poll()
        self.device.ConnectProfile.assert_not_called()
        self.target_properties['Connected'] = True
        self.now += 5
        self.poll()
        self.assertEqual(self.device.ConnectProfile.call_count, 1)
        self.target_properties['Connected'] = False
        self.now += 5
        self.poll()
        self.target_properties['Connected'] = True
        self.now += 5
        self.poll()
        self.assertEqual(self.device.ConnectProfile.call_count, 2)

    def test_standby_keeps_a_profile_connected_for_a_call(self):
        self.router.keep_connected = True
        self.poll()
        self.assertEqual(self.router.profile_device, '/org/bluez/hci1/dev_HU')
        self.properties['voiceCalls'] = []
        self.poll()
        self.device.DisconnectProfile.assert_not_called()
        self.assertEqual(self.router.standby_device, '/org/bluez/hci1/dev_HU')
        self.device.ConnectProfile.assert_called_once()

    def test_call_reconnects_the_authenticated_hu_and_enables_native_duplex_audio(self):
        self.poll()
        self.device.ConnectProfile.assert_called_once_with(HFP_HEADSET, timeout=6)
        self.router.routes.Disable.assert_called_once_with(BLUETOOTH_OVERRIDE)
        self.router.routes.Enable.assert_not_called()
        self.assertEqual(self.router.profile_device, '/org/bluez/hci1/dev_HU')
        self.assertTrue(self.router.owns_override)

    def test_existing_acl_still_connects_the_hfp_profile(self):
        self.target_properties['Connected'] = True
        self.poll()
        self.device.ConnectProfile.assert_called_once_with(HFP_HEADSET, timeout=6)

    def test_existing_hfp_and_native_audio_selection_are_preserved(self):
        self.target_properties['Connected'] = True
        self.device.ConnectProfile.side_effect = BluezError('org.bluez.Error.AlreadyConnected')
        self.features[:] = [(BLUETOOTH_OVERRIDE, 1, 0)]
        self.poll()
        self.router.routes.Enable.assert_not_called()
        self.router.routes.Disable.assert_not_called()
        self.properties['voiceCalls'] = []
        self.poll()
        self.device.DisconnectProfile.assert_not_called()
        self.router.routes.Disable.assert_not_called()

    def test_automatic_route_is_applied_once_so_the_user_can_switch_to_the_phone(self):
        self.poll()
        self.features[:] = [(BLUETOOTH_OVERRIDE, 1, 1)]
        self.poll()
        self.router.routes.Disable.assert_called_once_with(BLUETOOTH_OVERRIDE)
        self.device.ConnectProfile.assert_called_once()

    def test_a_user_selected_speaker_is_preserved(self):
        self.properties['audioMode'] = 'ihf'
        self.poll()
        self.router.routes.Disable.assert_not_called()

    def test_ringing_waits_for_the_native_call_audio_grant(self):
        self.properties['isAudioRouted'] = False
        self.poll()
        self.device.ConnectProfile.assert_called_once()
        self.router.routes.Disable.assert_not_called()
        self.properties['isAudioRouted'] = True
        self.poll()
        self.router.routes.Disable.assert_called_once_with(BLUETOOTH_OVERRIDE)

    def test_native_feature_becoming_available_is_observed_without_reconnecting(self):
        self.features[:] = [(BLUETOOTH_OVERRIDE, 0, 0)]
        self.poll()
        self.router.routes.Disable.assert_not_called()
        self.features[:] = [(BLUETOOTH_OVERRIDE, 1, 1)]
        self.poll()
        self.router.routes.Disable.assert_called_once_with(BLUETOOTH_OVERRIDE)
        self.device.ConnectProfile.assert_called_once()

    def test_call_ending_during_hfp_connect_releases_the_new_profile(self):
        def connect(*args, **kwargs):
            self.properties['voiceCalls'] = []
            self.target_properties['Connected'] = True
        self.device.ConnectProfile.side_effect = connect
        self.poll()
        self.router.routes.Disable.assert_not_called()
        self.device.DisconnectProfile.assert_called_once_with(HFP_HEADSET, timeout=5)

    def test_call_end_releases_only_the_temporary_feature_and_hfp_profile(self):
        self.poll()
        self.features[:] = [(BLUETOOTH_OVERRIDE, 1, 0)]
        self.properties['voiceCalls'] = []
        self.poll()
        self.router.routes.Enable.assert_called_once_with(BLUETOOTH_OVERRIDE)
        self.device.DisconnectProfile.assert_called_once_with(HFP_HEADSET, timeout=5)
        self.assertFalse(self.router.profile_requested)

    def test_projection_teardown_keeps_an_ongoing_native_call_connected(self):
        self.poll()
        self.features[:] = [(BLUETOOTH_OVERRIDE, 1, 0)]
        self.assertFalse(self.router.release())
        self.router.routes.Enable.assert_not_called()
        self.device.DisconnectProfile.assert_not_called()

    def test_replaced_bluez_lifetime_is_not_disconnected_during_cleanup(self):
        self.poll()
        self.properties['voiceCalls'] = []
        self.router.system.get_name_owner.return_value = ':1.99'
        self.poll()
        self.device.DisconnectProfile.assert_not_called()
        self.assertIsNone(self.router.profile_device)

    def test_disconnected_hfp_is_reacquired_during_the_call(self):
        self.poll()
        self.target_properties['Connected'] = False
        self.now += 6
        self.poll()
        self.assertEqual(self.device.ConnectProfile.call_count, 2)
        self.assertEqual(self.router.routes.Disable.call_count, 2)

    def test_hfp_loss_is_recovered_when_another_profile_keeps_the_acl_connected(self):
        self.poll()
        self.features[:] = [(BLUETOOTH_OVERRIDE, 0, 0)]
        self.poll()
        self.assertFalse(self.router.profile_requested)
        self.features[:] = [(BLUETOOTH_OVERRIDE, 1, 1)]
        self.poll()
        self.assertEqual(self.device.ConnectProfile.call_count, 2)

    def test_already_disconnected_profile_does_not_poison_cleanup(self):
        self.poll()
        self.properties['voiceCalls'] = []
        self.device.DisconnectProfile.side_effect = BluezError('org.bluez.Error.NotConnected')
        self.poll()
        self.assertIsNone(self.router.profile_device)
        self.assertFalse(self.router.profile_requested)

    def test_stop_during_hfp_connect_prevents_an_audio_route_change(self):
        self.device.ConnectProfile.side_effect = lambda *args, **kwargs: self.router.stop.set()
        self.poll()
        self.router.routes.Disable.assert_not_called()

    def test_a_call_starting_during_cleanup_keeps_the_hfp_profile(self):
        self.poll()
        self.router.voice.GetAll.side_effect = [{'voiceCalls': []}, self.properties]
        self.assertFalse(self.router.release())
        self.router.routes.Enable.assert_not_called()
        self.device.DisconnectProfile.assert_not_called()

    def test_monitor_start_is_idempotent(self):
        with patch('carplay_proto.callaudio.threading.Thread') as thread:
            self.router.start()
            self.router.start()
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()

    def test_new_call_is_routed_again_without_a_gap_between_poll_intervals(self):
        self.poll()
        self.properties['voiceCalls'] = ['/call/2']
        self.poll()
        self.assertEqual(self.router.routes.Disable.call_count, 2)
        self.device.ConnectProfile.assert_called_once()

    def test_profile_connection_failures_are_bounded(self):
        self.device.ConnectProfile.side_effect = BluezError('org.bluez.Error.Failed')
        for _ in range(5):
            self.poll()
            self.now += 6
        self.assertEqual(self.device.ConnectProfile.call_count, 3)
        self.router.routes.Disable.assert_not_called()

    def test_accepted_hfp_requests_wait_for_native_audio_and_retry_with_a_bound(self):
        self.features[:] = [(BLUETOOTH_OVERRIDE, 0, 0)]
        self.poll()
        self.now += 1
        self.poll()
        self.device.ConnectProfile.assert_called_once()
        for _ in range(4):
            self.now += 6
            self.poll()
            self.poll()
        self.assertEqual(self.device.ConnectProfile.call_count, 3)
        self.router.routes.Disable.assert_not_called()
        self.assertFalse(self.router.profile_requested)

    def test_native_audio_can_become_available_after_connection_attempts_are_exhausted(self):
        self.features[:] = [(BLUETOOTH_OVERRIDE, 0, 0)]
        for _ in range(3):
            self.poll()
            self.now += 6
            self.poll()
        self.features[:] = [(BLUETOOTH_OVERRIDE, 1, 1)]
        self.poll()
        self.assertEqual(self.device.ConnectProfile.call_count, 3)
        self.router.routes.Disable.assert_called_once_with(BLUETOOTH_OVERRIDE)

    def test_a_disconnected_target_does_not_cause_unbounded_accepted_requests(self):
        self.features[:] = [(BLUETOOTH_OVERRIDE, 0, 0)]
        self.device.ConnectProfile.side_effect = None
        for _ in range(6):
            self.poll()
            self.now += 6
        self.assertEqual(self.device.ConnectProfile.call_count, 3)
        self.router.routes.Disable.assert_not_called()

    def test_an_accepted_request_waits_for_the_target_connection_before_selecting_audio(self):
        self.device.ConnectProfile.side_effect = None
        self.poll()
        self.router.routes.Disable.assert_not_called()
        self.target_properties['Connected'] = True
        self.poll()
        self.router.routes.Disable.assert_called_once_with(BLUETOOTH_OVERRIDE)
        self.device.ConnectProfile.assert_called_once()

    def test_cleanup_preserves_a_manually_restored_phone_override(self):
        self.poll()
        self.properties['voiceCalls'] = []
        self.poll()
        self.router.routes.Enable.assert_not_called()
        self.device.DisconnectProfile.assert_called_once()

    def test_cleanup_does_not_enable_an_unavailable_phone_override(self):
        self.poll()
        self.features[:] = [(BLUETOOTH_OVERRIDE, 0, 0)]
        self.properties['voiceCalls'] = []
        self.poll()
        self.router.routes.Enable.assert_not_called()
        self.device.DisconnectProfile.assert_called_once()

    def test_unpaired_or_non_hfp_targets_are_not_connected(self):
        for values in ({'Paired': False, 'UUIDs': [HFP_HEADSET]}, {'Paired': True, 'UUIDs': []}):
            with self.subTest(values=values):
                self.target_properties.clear()
                self.target_properties.update(values)
                self.poll()
        self.device.ConnectProfile.assert_not_called()

    def test_another_connected_hfp_device_prevents_ambiguous_microphone_routing(self):
        self.objects['/org/bluez/hci1/dev_HEADSET'] = {
            'org.bluez.Device1': {'Paired': True, 'Connected': True, 'UUIDs': [HFP_HEADSET]}}
        self.poll()
        self.device.ConnectProfile.assert_not_called()
        self.router.routes.Disable.assert_not_called()

    def test_saved_device_identity_is_resolved_after_adapter_renumbering(self):
        self.objects = {'/org/bluez/hci4/dev_HU': {'org.bluez.Device1': self.target_properties}}
        self.poll()
        self.assertEqual(self.router.profile_device, '/org/bluez/hci4/dev_HU')

    def test_route_diagnostics_include_output_and_microphone_without_call_identifiers(self):
        self.router.routes.GetAll.side_effect = None
        self.router.routes.GetAll.return_value = ('bthfpforcall', 1, 'bthfpforcall', 2, self.features)
        self.poll()
        message = self.router.log.call_args.args[0]
        self.assertIn('output=bthfpforcall input=bthfpforcall', message)
        self.assertIn('PhoneOverride=True', message)
        self.assertNotIn('/call/1', message)


if __name__ == '__main__':
    unittest.main()
