import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('pulse',Path(__file__).resolve().parents[1]/'scripts/pulse-capture.py')
pulse=importlib.util.module_from_spec(spec);spec.loader.exec_module(pulse)
class PrivateMuteTests(unittest.TestCase):
    def test_unmute_only_active_private_output(self):
        def block(i,sink,corked,mute):return f'Sink Input #{i}\n Sink: {sink}\n Corked: {corked}\n Mute: {mute}\n'
        text=block(1,9,'no','yes')+block(2,0,'no','yes')+block(3,9,'yes','yes')+block(4,9,'no','no')
        self.assertEqual([x['id'] for x in pulse.muted_cast_streams(text,9)],['1'])

    def test_transient_audio_restart_retries_sink_creation(self):
        from unittest.mock import patch
        import subprocess
        with patch.object(pulse,'pactl',side_effect=[subprocess.CalledProcessError(1,'pactl'),'12']),patch.object(pulse.time,'sleep'):
            self.assertEqual(pulse.load_private_sink('sailplay_cast_test'),'12')

    def test_capture_does_not_force_tight_playback_deadline(self):
        self.assertEqual(pulse.C.sizeof(pulse.BufferAttr),20)
        attrs=pulse.capture_buffer_attr()
        self.assertEqual(attrs.fragsize,48000)
        self.assertEqual(attrs.maxlength,0xffffffff)

    def test_zero_volume_private_playback_is_selected_without_other_outputs(self):
        text='Sink Input #1\n Sink: 9\n Corked: no\n Mute: yes\n Volume: front-left: 0 / 0%, front-right: 0 / 0%\nSink Input #2\n Sink: 0\n Corked: no\n Mute: yes\n Volume: mono: 0 / 0%\n'
        selected=pulse.private_playback(text,9)
        self.assertEqual(len(selected),1);self.assertEqual(selected[0][0]['id'],'1');self.assertEqual(selected[0][1],['0','0'])
    def test_restore_matches_private_sink_and_player_identity(self):
        from unittest.mock import patch,call
        text='Sink Input #1\n Sink: 9\n application.process.binary = "player"\n'
        state={'cast':'sailplay_cast_123','streams':{'1':{'binary':'player','volumes':['15246'],'mute':False},'2':{'binary':'other','volumes':['0'],'mute':True}}}
        def pactl(*args):
            if args==('list','short','sinks'):return '9 sailplay_cast_123 module-null-sink\n'
            if args==('list','sink-inputs'):return text
            return ''
        with patch.object(pulse,'pactl',side_effect=pactl) as mocked:
            pulse.restore_private_inputs(state)
            self.assertIn(call('set-sink-input-volume','1','15246'),mocked.call_args_list)
            self.assertIn(call('set-sink-input-mute','1','0'),mocked.call_args_list)
            self.assertFalse(any('2' in c.args for c in mocked.call_args_list))
