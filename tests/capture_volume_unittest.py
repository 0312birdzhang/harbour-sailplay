import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
import struct
from unittest.mock import patch,call

spec=importlib.util.spec_from_file_location('pulse_capture',Path(__file__).resolve().parents[1]/'scripts'/'pulse-capture.py')
capture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureVolumeTests(unittest.TestCase):
    def test_diagnostics_keep_route_state_without_song_metadata(self):
        output='''Sink Input #7
    Sink: 12
    Corked: no
    Mute: yes
    Volume: mono: 32768 / 50% / -18.06 dB
    application.process.binary = "jolla-mediaplayer"
    media.title = "Private song"
    media.filename = "/home/user/private.mp3"
'''
        state=capture.stream_diagnostics(output)
        self.assertEqual(state[0]['sink'],'12')
        self.assertEqual(state[0]['mute'],'yes')
        self.assertEqual(state[0]['application.process.binary'],'jolla-mediaplayer')
        self.assertNotIn('Private',json.dumps(state))
        self.assertNotIn('/home',json.dumps(state))

    def test_media_gain_uses_cubic_volume_and_ignores_corked_streams(self):
        output='''Sink Input #1
    Corked: no
    Mute: no
    Volume: mono: 32768 / 50% / -18.06 dB
    media.role = "music"
Sink Input #2
    Corked: yes
    Volume: mono: 65536 / 100% / 0.00 dB
'''
        self.assertEqual(capture.capture_gain(output),8.0)
        self.assertEqual(capture.capture_gain(output.replace('32768','1')),64.0)
        self.assertEqual(capture.capture_gain(output.replace('Mute: no','Mute: yes')),1.0)

    def test_pcm_gain_saturates_without_wrapping(self):
        pcm=struct.pack('<hhh',1000,20000,-20000)
        self.assertEqual(struct.unpack('<hhh',capture.audioop.mul(pcm,2,2)),(2000,32767,-32768))

    def test_recovery_restores_hardware_channels_before_unmuting(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'recovery.json'
            state={'default':'phone','cast':'cast','mutes':{'phone':False},'volumes':{'phone':['20000','24000']}}
            path.write_text(json.dumps(state))
            with patch.object(capture,'ROUTE_STATE',str(path)),patch.object(capture,'pactl',return_value='cast') as command:
                capture.restore_outputs()
                calls=command.call_args_list
                self.assertLess(calls.index(call('set-sink-volume','phone','20000','24000')),
                                calls.index(call('set-sink-mute','phone','0')))

    def test_failed_volume_recovery_does_not_unmute_or_delete_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'recovery.json'
            path.write_text(json.dumps({'mutes':{'phone':False},'volumes':{'phone':['20000']}}))
            def fail_volume(*args):
                if args[0]=='set-sink-volume':raise OSError('failed')
                return ''
            with patch.object(capture,'ROUTE_STATE',str(path)),patch.object(capture,'pactl',side_effect=fail_volume) as command:
                with self.assertRaises(OSError):capture.restore_outputs()
                self.assertNotIn(call('set-sink-mute','phone','0'),command.call_args_list)
            self.assertTrue(path.exists())

    def test_abnormal_recovery_unloads_only_owned_sink_before_restoring_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'recovery.json'
            path.write_text(json.dumps({'cast':'sailplay_cast_1','mutes':{'phone':False},'volumes':{'phone':['20000']}}))
            modules='1\tmodule-null-sink\tsink_name=sailplay_cast_1 rate=48000\n2\tmodule-null-sink\tsink_name=sailplay_cast_12\n'
            with patch.object(capture,'ROUTE_STATE',str(path)),patch.object(capture,'pactl',return_value=modules) as command:
                capture.restore_outputs()
                calls=command.call_args_list
                self.assertLess(calls.index(call('unload-module','1')),calls.index(call('set-sink-volume','phone','20000')))
                self.assertNotIn(call('unload-module','2'),calls)

    def test_hardware_volume_parser_preserves_channel_values(self):
        self.assertEqual(capture.hardware_volumes('''Sink #0
    Name: sink.primary_output
    Volume: front-left: 20000 / 31% / -30 dB, front-right: 24000 / 37% / -26 dB
'''),{'sink.primary_output':['20000','24000']})

    def test_output_recovery_restores_mutes_and_only_our_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'recovery.json'
            state={'default':'sink.null','cast':'sailplay_cast_1','mutes':{'sink.primary_output':False,'sink.fast':True}}
            for current in ('sailplay_cast_1','user_selected_sink'):
                path.write_text(json.dumps(state))
                with patch.object(capture,'ROUTE_STATE',str(path)),patch.object(capture,'pactl',return_value=current) as command:
                    capture.restore_outputs()
                    self.assertIn(call('set-sink-mute','sink.primary_output','0'),command.call_args_list)
                    self.assertIn(call('set-sink-mute','sink.fast','1'),command.call_args_list)
                    self.assertEqual(call('set-default-sink','sink.null') in command.call_args_list,current=='sailplay_cast_1')
                self.assertFalse(path.exists())

    def test_preserves_individual_channel_volumes(self):
        output='''Sink Input #244
    Volume: front-left: 23722 / 36% / -26.48 dB, front-right: 30000 / 46% / -20.37 dB
    Base Volume: 65536 / 100% / 0.00 dB
Sink Input #245
    Volume: mono: 65536 / 100% / 0.00 dB
'''
        self.assertEqual(capture.playback_volumes(output),{'244':['23722','30000'],'245':['65536']})

    def test_missing_volume_does_not_invent_restore_value(self):
        self.assertEqual(capture.playback_volumes('Sink Input #1\n    Mute: no\n'),{})
