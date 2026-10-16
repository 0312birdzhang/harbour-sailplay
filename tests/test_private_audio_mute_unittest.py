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

    def test_capture_requests_one_aac_frame_per_pa_fragment(self):
        self.assertEqual(pulse.C.sizeof(pulse.BufferAttr),20)
        attrs=pulse.capture_buffer_attr()
        self.assertEqual(attrs.fragsize,1024*2*2)
        self.assertEqual(attrs.maxlength,0xffffffff)
