import importlib.util
from pathlib import Path
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
import types
import os
import subprocess
import sys
import tempfile
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

    def test_only_droid_hal_sinks_are_muted(self):
        listing = ('0\tsink.primary_output\tmodule-alsa-sink.c\ts16le 2ch 48000Hz\tRUNNING\n'
                   '1\tsink.null\tmodule-null-sink.c\ts16le 2ch 48000Hz\tSUSPENDED\n'
                   '2\tsink.primary\tmodule-droid-card.c\ts16le 2ch 48000Hz\tIDLE\n'
                   '3\tsailplay_cast_9\tmodule-null-sink.c\ts16le 2ch 48000Hz\tRUNNING\n')
        # Muting an ALSA primary output makes the policy attenuate the cast sink.
        self.assertEqual(pulse.hardware_sinks(listing), ['sink.primary'])

    def test_capture_never_makes_the_private_sink_the_default(self):
        # A default private sink lets the Sailfish policy attenuate its streams.
        import inspect
        source = inspect.getsource(pulse.main)
        self.assertNotIn("pactl('set-default-sink',name)", source)

    def test_system_volume_restores_exact_step_and_checks_result(self):
        from unittest.mock import Mock, patch
        import types
        props=Mock()
        props.GetAll.return_value={'StepCount':16,'CurrentStep':15,'CallState':'inactive'}
        props.Get.return_value=4
        old={'mainVolume':{'CurrentStep':4,'StepCount':16,'CallState':'inactive'}}
        with patch.object(pulse,'main_volume_properties',return_value=props), patch.dict('sys.modules',{'dbus':types.SimpleNamespace(UInt32=int)}):
            pulse.restore_main_volume(old)
            props.Set.assert_called_once_with('com.Meego.MainVolume2','CurrentStep',4)
            props.Get.return_value=15
            with self.assertRaises(RuntimeError):pulse.restore_main_volume(old)

    def test_system_volume_restored_before_hardware_unmute_and_record_removal(self):
        import json,tempfile
        from unittest.mock import patch
        from pathlib import Path
        calls=[]
        state={'mutes':{'sink.primary_output':False},'volumes':{'sink.primary_output':['12000','12000']},'streams':{},'mainVolume':{}}
        with tempfile.TemporaryDirectory() as directory:
            record=Path(directory)/'recovery.json';record.write_text(json.dumps(state))
            def pactl(*args):
                calls.append(args)
                return ''
            def restore(state):
                self.assertTrue(record.exists())
                calls.append(('restore-system-step',))
            with patch.object(pulse,'ROUTE_STATE',str(record)),patch.object(pulse,'pactl',side_effect=pactl),patch.object(pulse,'restore_main_volume',side_effect=restore):
                pulse.restore_outputs()
            self.assertLess(calls.index(('restore-system-step',)),calls.index(('set-sink-mute','sink.primary_output','0')))
            self.assertFalse(record.exists())


class ChangedVolumeContextTests(unittest.TestCase):
    def test_bluetooth_to_speaker_change_does_not_poison_next_capture(self):
        import json,tempfile,types
        from pathlib import Path
        from unittest.mock import Mock,patch,call
        props=Mock()
        props.GetAll.return_value={'CurrentStep':2,'StepCount':12,'CallState':'inactive'}
        state={'mutes':{'sink.primary_output':False},'volumes':{'sink.primary_output':['20000']},
               'mainVolume':{'CurrentStep':6,'StepCount':20,'CallState':'background'}}
        with tempfile.TemporaryDirectory() as directory:
            record=Path(directory)/'recovery.json';record.write_text(json.dumps(state))
            with patch.object(pulse,'ROUTE_STATE',str(record)),patch.object(pulse,'main_volume_properties',return_value=props),patch.dict('sys.modules',{'dbus':types.SimpleNamespace(UInt32=int)}),patch.object(pulse,'pactl',return_value='') as command:
                pulse.restore_outputs()
                self.assertFalse(record.exists())
                props.Set.assert_not_called()
                self.assertIn(call('set-sink-mute','sink.primary_output','0'),command.call_args_list)
                command.reset_mock()
                pulse.restore_outputs()
                command.assert_not_called()


class StreamRestoreEntryTests(unittest.TestCase):
    @contextmanager
    def backend(self,volume=65536,device='sailplay_cast_9',mute=False):
        connection,extension,properties,entry=Mock(),Mock(),Mock(),Mock()
        values={'Device':device,'Volume':[[0,volume]],'Mute':mute}
        properties.GetAll.return_value=values
        interfaces={'org.PulseAudio.Ext.StreamRestore1':extension,
                    'org.freedesktop.DBus.Properties':properties,
                    'org.PulseAudio.Ext.StreamRestore1.RestoreEntry':entry}
        class MissingEntry(Exception):
            def get_dbus_name(self):return 'org.PulseAudio.Error.NotFound'
        module=types.SimpleNamespace(Interface=lambda obj,iface:interfaces[iface],
            Array=lambda values,signature:values,DBusException=MissingEntry)
        with patch.object(pulse,'pulse_connection',return_value=connection), \
             patch.dict('sys.modules',{'dbus':module}),patch.object(pulse,'save_recovery') as save:
            yield connection,extension,properties,entry,save,MissingEntry
        connection.close.assert_called_once()

    def test_remembers_entry_before_stream_is_moved(self):
        state={'cast':'sailplay_cast_9'}
        with self.backend(volume=16384,device='') as (_,_,_,_,save,_):
            pulse.remember_stream_restore(state,{'module-stream-restore.id':'feedback'})
            self.assertEqual(state['restoreEntries']['feedback'],{'device':'','volume':[[0,16384]],'mute':False})
            save.assert_called_once_with(state)

    def test_repeated_boost_keeps_original_entry(self):
        old={'device':'phone','volume':[[0,16384]],'mute':False}
        state={'cast':'sailplay_cast_9','restoreEntries':{'feedback':old}}
        with self.backend() as (_,_,_,_,save,_):
            pulse.remember_stream_restore(state,{'module-stream-restore.id':'feedback'})
            self.assertEqual(state['restoreEntries']['feedback'],old)
            save.assert_not_called()

    def test_new_user_level_is_remembered_without_private_device(self):
        state={'cast':'sailplay_cast_9','restoreEntries':{'feedback':{'device':'phone','volume':[[0,16384]],'mute':False}}}
        with self.backend(volume=9000):
            pulse.remember_stream_restore(state,{'module-stream-restore.id':'feedback'})
            self.assertEqual(state['restoreEntries']['feedback'],{'device':'phone','volume':[[0,9000]],'mute':False})

    def test_finished_stream_restores_volume_and_device(self):
        state={'cast':'sailplay_cast_9','restoreEntries':{'feedback':{'device':'','volume':[[0,16384]],'mute':False}}}
        with self.backend() as (_,extension,_,_,_,_):
            pulse.restore_stream_entries(state)
            extension.AddEntry.assert_called_once_with('feedback','',[[0,16384]],False,False)

    def test_original_empty_channel_volume_is_restored(self):
        state={'cast':'sailplay_cast_9','restoreEntries':{'feedback':{'device':'','volume':[],'mute':False}}}
        with self.backend() as (_,extension,_,entry,save,_):
            pulse.restore_stream_entries(state)
            entry.Remove.assert_called_once()
            save.assert_called_once_with(state)
            self.assertEqual(state['pendingRestoreEntries']['feedback'],state['restoreEntries']['feedback'])
            extension.AddEntry.assert_called_once_with('feedback','',[],False,False)

    def test_interrupted_empty_volume_recreation_can_be_retried(self):
        old={'device':'','volume':[],'mute':False}
        state={'cast':'sailplay_cast_9','restoreEntries':{'feedback':old},'pendingRestoreEntries':{'feedback':old}}
        with self.backend() as (_,extension,_,_,_,missing):
            extension.GetEntryByName.side_effect=missing()
            pulse.restore_stream_entries(state)
            extension.AddEntry.assert_called_once_with('feedback','',[],False,False)

    def test_changed_user_volume_is_preserved_while_private_device_is_cleared(self):
        state={'cast':'sailplay_cast_9','restoreEntries':{'feedback':{'device':'','volume':[[0,16384]],'mute':False}}}
        with self.backend(volume=9000,mute=True) as (_,extension,_,_,_,_):
            pulse.restore_stream_entries(state)
            extension.AddEntry.assert_called_once_with('feedback','',[[0,9000]],True,False)

    def test_current_user_volume_mute_and_device_are_preserved(self):
        state={'cast':'sailplay_cast_9','restoreEntries':{'feedback':{'device':'phone','volume':[[0,16384]],'mute':False}}}
        with self.backend(volume=9000,device='headset',mute=True) as (_,extension,_,_,_,_):
            pulse.restore_stream_entries(state)
            extension.AddEntry.assert_not_called()

    def test_new_entry_is_removed_only_with_owned_boost(self):
        state={'cast':'sailplay_cast_9','restoreEntries':{'feedback':None}}
        with self.backend() as (_,_,_,entry,_,_):
            pulse.restore_stream_entries(state)
            entry.Remove.assert_called_once()
        with self.backend(volume=9000) as (_,_,_,entry,_,_):
            pulse.restore_stream_entries(state)
            entry.Remove.assert_not_called()

    def test_missing_original_entry_is_recorded(self):
        state={'cast':'sailplay_cast_9'}
        with self.backend() as (_,extension,_,_,_,missing):
            extension.GetEntryByName.side_effect=missing()
            pulse.remember_stream_restore(state,{'module-stream-restore.id':'feedback'})
            self.assertIsNone(state['restoreEntries']['feedback'])

    def test_already_removed_entry_does_not_block_recovery(self):
        state={'cast':'sailplay_cast_9','restoreEntries':{'feedback':None}}
        with self.backend() as (_,extension,_,_,_,missing):
            extension.GetEntryByName.side_effect=missing()
            pulse.restore_stream_entries(state)
            extension.AddEntry.assert_not_called()


class RoutingLockTests(unittest.TestCase):
    @unittest.skipIf(os.name=='nt','Production routing uses Unix flock')
    def test_recovery_waits_for_the_active_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            record=str(Path(directory)/'recovery.json')
            script='''import fcntl
descriptor=open(PATH,'a')
print('waiting',flush=True)
fcntl.flock(descriptor,fcntl.LOCK_EX)
print('locked',flush=True)
'''.replace('PATH',repr(record+'.lock'))
            with patch.object(pulse,'ROUTE_STATE',record):
                with pulse.routing_lock():
                    process=subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.PIPE,text=True)
                    self.assertEqual(process.stdout.readline().strip(),'waiting')
                    self.assertIsNone(process.poll())
                output,_=process.communicate(timeout=3)
                self.assertEqual(process.returncode,0)
                self.assertEqual(output.strip(),'locked')
