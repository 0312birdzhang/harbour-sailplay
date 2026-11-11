import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch, call
import subprocess
import hashlib
import tempfile

spec = importlib.util.spec_from_file_location('audio_policy',
    Path(__file__).resolve().parents[1] / 'scripts' / 'reload-audio-policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class AudioPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy_check = patch.object(policy, 'policy_unchanged', return_value=False)
        self.policy_check.start()
        self.addCleanup(self.policy_check.stop)
        self.policy_path = patch.object(policy, 'PREVIOUS_POLICY_PATH')
        self.previous = self.policy_path.start()
        self.previous.exists.return_value = False
        self.addCleanup(self.policy_path.stop)

    def test_identical_policy_skips_the_global_reload(self):
        with patch.object(policy, 'policy_unchanged', return_value=True), \
             patch.object(policy.subprocess, 'check_output') as output, \
             patch.object(policy.subprocess, 'check_call') as run:
            policy.reload_policy()
        output.assert_not_called()
        run.assert_not_called()

    def test_changed_rpm_policy_uses_a_fresh_server_registration(self):
        self.previous.exists.return_value = True
        with patch.object(policy.subprocess, 'check_output', return_value=b'11\tmodule-policy-enforcement\t\n'), \
             patch.object(policy.subprocess, 'check_call') as run:
            policy.reload_policy()
        run.assert_called_once_with(['systemctl', '--user', 'restart', 'pulseaudio.service'], timeout=30)

    def test_reload_only_policy_and_preserve_arguments(self):
        modules = b'8\tmodule-null-sink\tsink_name=sink.null\t\n11\tmodule-policy-enforcement\tfoo=bar\t\n'
        with patch.object(policy.subprocess, 'check_output', return_value=modules), \
             patch.object(policy, 'playback_routes', return_value={}), \
             patch.object(policy.subprocess, 'check_call') as run:
            policy.reload_policy()
        self.assertEqual(run.call_args_list, [
            call(['pactl', 'unload-module', '11'], timeout=5),
            call(['pactl', 'load-module', 'module-policy-enforcement', 'foo=bar'], timeout=5)])

    def test_no_policy_does_not_load_new_global_module(self):
        with patch.object(policy.subprocess, 'check_output', return_value=b'8\tmodule-null-sink\t\n'), \
             patch.object(policy.subprocess, 'check_call') as run:
            policy.reload_policy()
        run.assert_not_called()

    def test_failed_activation_attempts_to_restore_policy(self):
        with patch.object(policy.subprocess, 'check_output', return_value=b'11\tmodule-policy-enforcement\t\n'), \
             patch.object(policy, 'playback_routes', return_value={}), \
             patch.object(policy.subprocess, 'check_call', side_effect=[None,
                 subprocess.CalledProcessError(1, 'load'), None]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                policy.reload_policy()
        self.assertEqual(run.call_args_list[-1],
                         call(['pactl', 'load-module', 'module-policy-enforcement'], timeout=5))

    def test_snapshot_uses_sink_names_and_stream_identity(self):
        outputs = [b'1\tsink.deep_buffer\tmodule-droid-card.c\n3\tsink.null\tmodule-null-sink.c\n',
                   b'42\t1\t8\tprotocol-native.c\ts16le 2ch 44100Hz\n']
        with patch.object(policy.subprocess, 'check_output', side_effect=outputs):
            self.assertEqual(policy.playback_routes(),
                             {'42': ('sink.deep_buffer', ['8', 'protocol-native.c', 's16le', '2ch', '44100Hz'])})

    def test_reload_restores_existing_stream_from_null_output(self):
        previous = {'42': ('sink.deep_buffer', ['8', 'protocol-native.c'])}
        current = {'42': ('sink.null', ['8', 'protocol-native.c'])}
        with patch.object(policy, 'playback_routes', return_value=current), \
             patch.object(policy.subprocess, 'check_call') as run:
            policy.restore_playback_routes(previous)
        run.assert_called_once_with(['pactl', 'move-sink-input', '42', 'sink.deep_buffer'], timeout=5)

    def test_finished_replaced_and_user_routed_streams_are_preserved(self):
        previous = {'42': ('sink.deep_buffer', ['8']), '43': ('sink.fast', ['9']),
                    '44': ('sink.fast', ['10']), '45': ('sink.null', ['11'])}
        current = {'43': ('sink.null', ['99']), '44': ('headset', ['10']), '45': ('sink.null', ['11'])}
        with patch.object(policy, 'playback_routes', return_value=current), \
             patch.object(policy.subprocess, 'check_call') as run:
            policy.restore_playback_routes(previous)
        run.assert_not_called()

    def test_stream_ending_during_route_restore_is_harmless(self):
        previous = {'42': ('sink.deep_buffer', ['8'])}
        with patch.object(policy, 'playback_routes', side_effect=[{'42': ('sink.null', ['8'])}, {}]), \
             patch.object(policy.subprocess, 'check_call', side_effect=subprocess.CalledProcessError(1, 'move')):
            policy.restore_playback_routes(previous)

    def test_failed_reload_still_restores_existing_stream_routes(self):
        routes = {'42': ('sink.deep_buffer', ['8'])}
        with patch.object(policy.subprocess, 'check_output', return_value=b'11\tmodule-policy-enforcement\t\n'), \
             patch.object(policy, 'playback_routes', return_value=routes), \
             patch.object(policy, 'restore_playback_routes') as restore, \
             patch.object(policy.subprocess, 'check_call', side_effect=[None,
                 subprocess.CalledProcessError(1, 'load'), None]):
            with self.assertRaises(subprocess.CalledProcessError):
                policy.reload_policy()
        restore.assert_called_once_with(routes)


class PolicyIdentityTests(unittest.TestCase):
    def test_previous_installed_policy_is_compared_by_content(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / 'policy.conf'
            previous = Path(directory) / 'previous.sha256'
            current.write_bytes(b'capture policy\n')
            previous.write_text(hashlib.sha256(current.read_bytes()).hexdigest())
            with patch.object(policy, 'POLICY_PATH', current), patch.object(policy, 'PREVIOUS_POLICY_PATH', previous):
                self.assertTrue(policy.policy_unchanged())
                current.write_bytes(b'updated policy\n')
                self.assertFalse(policy.policy_unchanged())
                previous.unlink()
                self.assertFalse(policy.policy_unchanged())
