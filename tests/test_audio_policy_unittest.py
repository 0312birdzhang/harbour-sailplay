import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch, call
import subprocess

spec = importlib.util.spec_from_file_location('audio_policy',
    Path(__file__).resolve().parents[1] / 'scripts' / 'reload-audio-policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class AudioPolicyTests(unittest.TestCase):
    def test_reload_only_policy_and_preserve_arguments(self):
        modules = b'8\tmodule-null-sink\tsink_name=sink.null\t\n11\tmodule-policy-enforcement\tfoo=bar\t\n'
        with patch.object(policy.subprocess, 'check_output', return_value=modules), \
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
             patch.object(policy.subprocess, 'check_call', side_effect=[None,
                 subprocess.CalledProcessError(1, 'load'), None]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                policy.reload_policy()
        self.assertEqual(run.call_args_list[-1],
                         call(['pactl', 'load-module', 'module-policy-enforcement'], timeout=5))
