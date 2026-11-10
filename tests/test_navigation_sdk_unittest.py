"""Public navigation, legacy compatibility and provider selection regressions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from carplay_proto.navigation import NavigationSubscription, START
from carplay_proto.navigationadapter import organicmaps_snapshot, meters
from carplay_proto.navigationproviders import ProviderNavigationFeed, SdkNavigationFeed
from carplay_proto.navigationsender import NavigationSender
from carplay_proto.wire import Frame, encode_param
from sailplay_sdk.contract import NAVIGATION_INTERFACE, signatures
from sailplay_sdk.discovery import discover, read_declaration
from sailplay_sdk.guidance import FIELDS, guidance, validate_guidance
from sailplay_sdk.model import Fault, MAX_UINT64


def active_guidance():
    return guidance('active', updated_ms=19000, maneuver='turn-left', nextDistanceMeters=200,
                    remainingDistanceMeters=12300, remainingSeconds=300,
                    currentRoad='当前道路', nextRoad='Next road', destination='Destination')


class GuidanceTests(unittest.TestCase):
    def test_navigation_xml(self):
        self.assertEqual(signatures(NAVIGATION_INTERFACE, 'GetGuidance'), ('', 'ta{sv}'))
        self.assertEqual(signatures(NAVIGATION_INTERFACE, 'GuidanceChanged', 'signal'), ('', 'ta{sv}'))

    def test_complete_model_and_si_units(self):
        value = validate_guidance(active_guidance(), 20000)
        self.assertEqual(set(value), FIELDS)
        self.assertEqual(value['nextDistanceMeters'], 200.0)
        self.assertEqual(value['remainingSeconds'], 300)

    def test_missing_and_unknown_fields_fail(self):
        for key in FIELDS:
            value = active_guidance()
            del value[key]
            with self.subTest(key=key), self.assertRaises(Fault):
                validate_guidance(value)
        with self.assertRaises(Fault):
            validate_guidance(dict(active_guidance(), unknown=1))

    def test_malformed_fields_fail(self):
        cases = (('state', 'invalid'), ('state', []), ('mode', 'spaceship'), ('maneuver', 2),
                 ('maneuver', 'raw-map-turn'), ('exitNumber', -1), ('exitNumber', 1 << 32),
                 ('exitNumber', True), ('drivingSide', 'unknown'), ('remainingSeconds', MAX_UINT64 + 1),
                 ('remainingSeconds', True), ('updatedMs', True), ('updatedMs', -1),
                 ('nextDistanceMeters', float('nan')), ('nextDistanceMeters', float('inf')),
                 ('nextDistanceMeters', -1), ('nextDistanceMeters', 1 << 4096),
                 ('nextDistanceMeters', True), ('currentRoad', 'x\0y'),
                 ('nextRoad', 'x' * 1025), ('destination', None))
        for key, invalid in cases:
            value = active_guidance()
            value[key] = invalid
            with self.subTest(key=key, value=invalid), self.assertRaises(Fault):
                validate_guidance(value)

    def test_uint64_duration_and_unicode_text_are_supported(self):
        value = active_guidance()
        value.update(remainingSeconds=MAX_UINT64, currentRoad='🚗' * 1024)
        self.assertEqual(validate_guidance(value)['remainingSeconds'], MAX_UINT64)

    def test_heartbeat_does_not_extend_guidance_age(self):
        with self.assertRaises(Fault):
            validate_guidance(active_guidance(), 29001)
        with self.assertRaises(Fault):
            validate_guidance(active_guidance(), 18999)

    def test_terminal_states_clear_previous_maneuver(self):
        for state in ('idle', 'stopped', 'arrived', 'unavailable'):
            value = active_guidance()
            value['state'] = state
            result = validate_guidance(value, 90000)
            with self.subTest(state=state):
                self.assertEqual(result['state'], state)
                self.assertEqual(result['maneuver'], 'unknown')
                self.assertEqual(result['nextRoad'], '')
                self.assertEqual(result['remainingDistanceMeters'], 0)

    def test_factory_validates_inactive_states(self):
        with self.assertRaises(Fault):
            guidance('incorrect', updated_ms=100)
        with self.assertRaises(Fault):
            guidance('idle', updated_ms=True)


class DeclarationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / 'example-navigation.desktop'
        self.text = ('[Desktop Entry]\nType=Application\nName=Example navigation\n'
                     'X-Sailplay-Service=org.example.Navigation\nX-Sailplay-ApiVersion=1\n'
                     'X-Sailplay-Capabilities=navigation;\nX-Sailplay-Presentation=template\n')
        self.path.write_text(self.text, encoding='utf-8')

    def test_default_versioned_path_and_template(self):
        declaration = read_declaration(self.path)
        self.assertEqual(declaration.path, '/org/sailplay/v1/App')
        self.assertEqual(declaration.application_id, 'example-navigation')
        self.assertTrue(declaration.navigation_template)
        self.assertEqual(len(discover(str(self.directory))), 1)

    def test_different_provider_needs_metadata_alone(self):
        second = self.directory / 'another-map.desktop'
        second.write_text(self.text.replace('org.example.Navigation', 'org.example.AnotherMap'), encoding='utf-8')
        declarations = discover(str(self.directory))
        self.assertEqual({item.service for item in declarations}, {'org.example.Navigation', 'org.example.AnotherMap'})

    def test_hidden_apps_require_explicit_discovery(self):
        self.path.write_text(self.text + 'NoDisplay=true\n', encoding='utf-8')
        self.assertIsNone(read_declaration(self.path))
        self.assertIsNotNone(read_declaration(self.path, include_hidden=True))

    def test_unsupported_or_malformed_declaration_is_rejected(self):
        changes = (('X-Sailplay-ApiVersion=1', 'X-Sailplay-ApiVersion=2'),
                   ('org.example.Navigation', ':1.23'), ('org.example.Navigation', 'oneword'),
                   ('org.example.Navigation', 'org.2Invalid'), ('navigation;', 'Navigation;'),
                   ('X-Sailplay-Presentation=template', 'X-Sailplay-Presentation=qml-plugin'))
        for old, new in changes:
            self.path.write_text(self.text.replace(old, new), encoding='utf-8')
            with self.subTest(new=new):
                self.assertIsNone(read_declaration(self.path))

    def test_unversioned_path_and_duplicate_keys_are_rejected(self):
        for extra in ('X-Sailplay-ObjectPath=/org/example/App\n', 'X-Sailplay-ApiVersion=1\n'):
            self.path.write_text(self.text + extra, encoding='utf-8')
            self.assertIsNone(read_declaration(self.path))


class NavigationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.subscription = NavigationSubscription()
        self.subscription.offer(Frame(START, encode_param(0, b'\0\x09')))
        self.snapshot = dict(providerId='example-map', instanceId='one', sequence=1, navigation=active_guidance())

    def frames(self, snapshot=None, sender=None):
        return (sender or NavigationSender()).frames(snapshot or self.snapshot, self.subscription, {0x5201, 0x5202})

    def test_neutral_provider_encodes_meters_and_driving_side(self):
        self.snapshot['navigation']['drivingSide'] = 'left'
        maneuver, route = [{item.id: item.payload for item in frame.parameters()} for frame in self.frames()]
        self.assertEqual(maneuver[3], bytes([47]))
        self.assertEqual(maneuver[8], b'\x01')
        self.assertEqual(int.from_bytes(route[10], 'big'), 200)
        self.assertEqual(route[11], b'200\0')
        self.assertEqual(route[12], b'\x02')

    def test_every_legacy_turn_keeps_its_receiver_value(self):
        expected = (0, 3, 2, 48, 14, 1, 47, 13, 4, 4, 6, 7, 6, 0, 10, 13, 14)
        raw = dict(pid=123, startTicks='99', sequence=1, navigation=dict(
            state='active', turn=0, exitNumber=0, nextDistance=200, nextDistanceUnit=0,
            remainingDistance=12.3, remainingDistanceUnit=1, remainingSeconds=300,
            currentRoad='Current', nextRoad='Next', destination='Destination'))
        for turn, value in enumerate(expected):
            raw['navigation']['turn'] = turn
            canonical = organicmaps_snapshot(raw)
            with self.subTest(turn=turn):
                parameters = {item.id: item.payload for item in self.frames(canonical)[0].parameters()}
                self.assertEqual(parameters[3], bytes([value]))
                self.assertEqual(parameters[8], b'\x01' if turn == 9 else b'\x00')

    def test_large_legacy_distance_saturates_before_rounding(self):
        self.assertEqual(meters(1e308, 3), 0xffffffff)

    def test_new_provider_instance_resends_equal_revision(self):
        sender = NavigationSender()
        self.assertEqual(len(self.frames(sender=sender)), 2)
        self.assertEqual(self.frames(sender=sender), [])
        self.snapshot['instanceId'] = 'replacement'
        self.assertEqual(len(self.frames(sender=sender)), 2)

    def test_unsupported_navigation_mode_clears_once(self):
        sender = NavigationSender()
        self.frames(sender=sender)
        self.snapshot['navigation']['mode'] = 'walking'
        self.assertEqual(len(self.frames(sender=sender)), 1)
        self.assertEqual(self.frames(sender=sender), [])


@unittest.skipUnless(hasattr(os, 'O_DIRECTORY') and hasattr(os, 'O_NOFOLLOW'), 'Linux file semantics')
class ProviderFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        self.directory = self.runtime / 'sailplay-navigation'
        self.directory.mkdir(parents=True, mode=0o700)
        self.proc = self.root / 'proc'
        (self.proc / 'sys/kernel/random').mkdir(parents=True)
        (self.proc / 'sys/kernel/random/boot_id').write_text('test-boot\n')
        self.feed = ProviderNavigationFeed(str(self.runtime), os.getuid(), str(self.proc), lambda: 20000)
        self.value = dict(schema=2, source='sailplay-sdk', pid=123, startTicks='777', bootId='test-boot',
                          applicationId='example-map', appKey='ZXhhbXBsZS1tYXA=', service='org.example.Navigation',
                          instanceId='backend-one', sequence='1', heartbeatMs=20000, navigation=active_guidance())

    def publish(self, value=None, pid=123):
        path = self.directory / ('sailplay-sdk-%d.json' % pid)
        path.write_text(json.dumps(value or self.value), encoding='utf-8')
        path.chmod(0o600)
        process = self.proc / str(pid)
        process.mkdir(exist_ok=True)
        (process / 'stat').write_text('%d (carui) ' % pid + ' '.join(['S'] + ['0'] * 18 + ['777']))
        (process / 'exe').symlink_to('/opt/sailplay/carui/carui')
        (process / 'environ').write_bytes(b'WAYLAND_DISPLAY=imira-comp-0\0')
        return path

    def test_sdk_feed_reaches_normal_vehicle_sender(self):
        self.publish()
        snapshot = self.feed.poll()
        self.assertEqual(snapshot['providerId'], 'example-map')
        self.assertEqual(self.feed.reason, 'sdk-ready')
        subscription = NavigationSubscription()
        subscription.offer(Frame(START, encode_param(0, b'\0\x09')))
        self.assertEqual(len(NavigationSender().frames(snapshot, subscription, {0x5201, 0x5202})), 2)

    def test_json_uint64_fields_are_lossless(self):
        self.value['sequence'] = str(MAX_UINT64)
        self.value['navigation']['remainingSeconds'] = str(MAX_UINT64)
        self.publish()
        snapshot = self.feed.poll()
        self.assertEqual(snapshot['sequence'], MAX_UINT64)
        self.assertEqual(snapshot['navigation']['remainingSeconds'], MAX_UINT64)

    def test_full_unicode_text_fields_fit_the_sdk_envelope(self):
        for key in ('currentRoad', 'nextRoad', 'destination'):
            self.value['navigation'][key] = '🚗' * 1024
        self.publish()
        snapshot = self.feed.poll()
        self.assertEqual(snapshot['navigation']['nextRoad'], '🚗' * 1024)

    def test_live_heartbeat_cannot_retain_expired_guidance(self):
        self.value['navigation']['updatedMs'] = 9999
        self.publish()
        self.assertIsNone(self.feed.poll())

    def test_process_exit_and_phone_side_publishers_are_rejected(self):
        self.publish()
        process = self.proc / '123'
        (process / 'environ').write_bytes(b'WAYLAND_DISPLAY=wayland-0\0')
        self.assertIsNone(self.feed.poll())
        (process / 'environ').write_bytes(b'WAYLAND_DISPLAY=imira-comp-0\0')
        (process / 'stat').unlink()
        self.assertIsNone(self.feed.poll())

    def test_pid_reuse_or_invalid_revision_is_rejected(self):
        path = self.publish()
        for key, invalid in (('startTicks', '778'), ('sequence', '0'), ('sequence', str(MAX_UINT64 + 1)),
                             ('sequence', 1), ('applicationId', 'x/y'), ('appKey', 'different'),
                             ('heartbeatMs', 16999), ('service', ':1.22')):
            value = copy.deepcopy(self.value)
            value[key] = invalid
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.subTest(key=key):
                self.assertIsNone(self.feed.poll())

    def test_multiple_sdk_providers_are_ambiguous(self):
        self.publish()
        second = dict(self.value, pid=124, applicationId='another-map', appKey='YW5vdGhlci1tYXA=')
        self.publish(second, 124)
        self.assertIsNone(self.feed.poll())
        self.assertEqual(self.feed.reason, 'ambiguous')


@unittest.skipUnless(shutil.which('dbus-run-session') and importlib.util.find_spec('dbus')
                     and importlib.util.find_spec('gi'), 'Linux D-Bus and GLib')
class NavigationBusTests(unittest.TestCase):
    def test_idle_exit_rechecks_activity_before_quitting(self):
        from unittest.mock import Mock, patch

        example_path = Path(__file__).resolve().parents[1] / 'sdk/examples/navigation-service.py'
        specification = importlib.util.spec_from_file_location('navigation_example', example_path)
        example = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(example)

        for activity in ('route', 'session', 'request'):
            provider = example.FakeNavigation.__new__(example.FakeNavigation)
            provider.loop = Mock()
            provider.active = False
            provider.stay_alive = False
            backend = Mock(session_count=0, pending_count=0)
            with self.subTest(activity=activity), patch.object(example.GLib, 'idle_add') as idle_add:
                provider.lifecycle(backend)
                idle_add.assert_called_once()
                callback = idle_add.call_args[0][0]
                provider.active = activity == 'route'
                backend.session_count = int(activity == 'session')
                backend.pending_count = int(activity == 'request')
                self.assertFalse(callback())
                provider.loop.quit.assert_not_called()

                provider.active = False
                backend.session_count = 0
                backend.pending_count = 0
                self.assertFalse(callback())
                provider.loop.quit.assert_called_once()

    def test_navigation_contract_and_lifecycle_on_private_bus(self):
        root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ, PYTHONPATH=str(root))
        result = subprocess.run(['dbus-run-session', '--', sys.executable,
                                 str(Path(__file__).with_name('navigation_sdk_bus_scenario.py'))],
                                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=35)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('NAVIGATION_SDK_BUS_PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
