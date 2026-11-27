import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
import queue
import unittest
from carplay_proto.mediakeys import consumer_layout,pressed_usages,MediaKeys
spec=importlib.util.spec_from_file_location('media_control',Path(__file__).resolve().parents[1]/'scripts/media-control.py')
control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
DESCRIPTOR=bytes.fromhex('050c0901a10115002506050c0a00000ab0000ab1000ab5000ab6000ab9000abc00750895018100c0')
class MediaTests(unittest.TestCase):
    def test_bluetooth_proxy_is_not_resumed_selected_or_paused(self):
        remote = 'org.mpris.MediaPlayer2.BIRD_PC'
        local = 'org.mpris.MediaPlayer2.music'
        bus = Mock()
        bus.list_names.return_value = [remote, local]
        bus.call_blocking.side_effect = lambda *args, **kwargs: 123 if args[5][0] == remote else 456
        bus.get_object.side_effect = lambda name, path: name
        players = {name: Mock() for name in [remote, local]}
        def interface(obj, name):
            if name == 'org.freedesktop.DBus.Properties':
                return SimpleNamespace(GetAll=lambda *a, **k: {'PlaybackStatus': 'Playing', 'CanPlay': True, 'CanPause': True})
            return players[obj]
        with patch.object(control.os, 'readlink', side_effect=lambda path: '/usr/bin/mpris-proxy' if '/123/' in path else '/usr/bin/player'):
            self.assertEqual(control.control(bus, 'ResumePreferred', interface, (remote, '')), 'no eligible player')
            self.assertIn(local, control.control(bus, 'ResumePreferred', interface))
            self.assertIn(local, control.control(bus, 'PausePlaying', interface))
        players[remote].Play.assert_not_called()
        players[remote].Pause.assert_not_called()
        players[local].Play.assert_called_once()

    def test_disconnect_pauses_all_playing_players_despite_stale_selection(self):
        names=['org.mpris.MediaPlayer2.music','org.mpris.MediaPlayer2.system','org.mpris.MediaPlayer2.paused']
        bus=Mock();bus.list_names.return_value=names;bus.get_object.side_effect=lambda name,path:name
        players={name:Mock() for name in names}
        def interface(obj,name):
            if name=='org.freedesktop.DBus.Properties':
                return SimpleNamespace(GetAll=lambda *a,**k:{'PlaybackStatus':'Paused' if obj.endswith('paused') else 'Playing'})
            return players[obj]
        result=control.control(bus,'PausePlaying',interface,('org.mpris.MediaPlayer2.gone','missing'))
        self.assertIn(names[0],result);self.assertIn(names[1],result)
        players[names[0]].Pause.assert_called_once();players[names[1]].Pause.assert_called_once()
        players[names[2]].Pause.assert_not_called()
    def test_empty_stock_player_loads_complete_queue_and_pauses_previous(self):
        old='org.mpris.MediaPlayer2.old';native='org.mpris.MediaPlayer2.jolla-mediaplayer.instance42'
        bus=Mock();bus.list_names.return_value=[old,native]
        bus.get_object.side_effect=lambda name,path:name
        players={old:Mock(),native:Mock(),'com.jolla.mediaplayer':Mock()}
        players['com.jolla.mediaplayer'].snapshot.return_value='{"ready":true,"index":-1,"items":[{"uri":"file:///music/first.mp3"},{"uri":"file:///music/second.mp3"}]}'
        players['com.jolla.mediaplayer'].playIndex.return_value=True
        def interface(obj,name):
            if name=='org.freedesktop.DBus.Properties':
                return SimpleNamespace(GetAll=lambda *a,**k:{'CanControl':True,'CanPause':True,'CanPlay':obj==old,
                                                           'PlaybackStatus':'Playing' if obj==old else 'Stopped'})
            return players[obj]
        uri='file:///music/first.mp3'
        control.control(bus,'PlayExclusive',interface,(native,''),uri)
        players[old].Pause.assert_called_once()
        players['com.jolla.mediaplayer'].playIndex.assert_called_once_with(0,signature='i',timeout=2)
        players[native].Play.assert_not_called()
    def test_exclusive_play_pauses_other_player_and_restores_on_failure(self):
        bus=Mock();bus.list_names.return_value=['org.mpris.MediaPlayer2.old','org.mpris.MediaPlayer2.target']
        bus.get_object.side_effect=lambda name,path:name
        players={name:Mock() for name in bus.list_names.return_value}
        def interface(obj,name):
            if name=='org.freedesktop.DBus.Properties':
                return SimpleNamespace(GetAll=lambda *a,**k:{'PlaybackStatus':'Playing' if obj.endswith('old') else 'Paused',
                                                           'CanPlay':True,'CanPause':True})
            return players[obj]
        target='org.mpris.MediaPlayer2.target';old='org.mpris.MediaPlayer2.old'
        control.control(bus,'PlayExclusive',interface,(target,''))
        players[old].Pause.assert_called_once();players[target].Play.assert_called_once()
        players[target].Play.side_effect=RuntimeError('target failed')
        with self.assertRaises(RuntimeError):control.control(bus,'PlayExclusive',interface,(target,''))
        players[old].Play.assert_called_once()

    def test_selected_player_without_capability_does_not_control_another_player(self):
        bus=Mock();bus.list_names.return_value=['org.mpris.MediaPlayer2.old','org.mpris.MediaPlayer2.target']
        bus.get_object.side_effect=lambda name,path:name
        calls=[]
        def interface(obj,name):
            if name=='org.freedesktop.DBus.Properties':
                return SimpleNamespace(GetAll=lambda *a,**k:{'CanPlay':obj.endswith('old'),'PlaybackStatus':'Playing'})
            calls.append(obj);return Mock()
        self.assertEqual(control.control(bus,'Play',interface,('org.mpris.MediaPlayer2.target','')),'no eligible player')
        self.assertEqual(calls,[])
    def test_audio_ready_resumes_only_once(self):
        m=MediaKeys.__new__(MediaKeys);m.active=False;m.pending=queue.Queue()
        with patch('carplay_proto.mediakeys.os.open',return_value=9), patch('carplay_proto.mediakeys.os.close'):
            m.started();m.started()
        self.assertEqual(m.pending.get_nowait(),'ResumePreferred')
        self.assertTrue(m.pending.empty())

    def test_remembered_player_receives_resume_and_hardware_keys(self):
        bus=Mock();bus.list_names.return_value=['org.mpris.MediaPlayer2.other','org.mpris.MediaPlayer2.music']
        bus.get_object.side_effect=lambda name,path:name
        players={name:Mock() for name in bus.list_names.return_value}
        def interface(obj,name):
            if name=='org.freedesktop.DBus.Properties':
                return SimpleNamespace(GetAll=lambda iface,**kw:
                    {'DesktopEntry':'music' if obj.endswith('music') else 'other'} if iface=='org.mpris.MediaPlayer2' else
                    {'PlaybackStatus':'Paused' if obj.endswith('music') else 'Playing','CanPlay':True,'CanGoNext':True})
            return players[obj]
        preferred=('org.mpris.MediaPlayer2.music','music')
        control.control(bus,'ResumePreferred',interface,preferred)
        players[preferred[0]].Play.assert_called_once()
        control.control(bus,'Next',interface,preferred)
        players[preferred[0]].Next.assert_called_once()
        players['org.mpris.MediaPlayer2.other'].Play.assert_not_called()
        self.assertEqual(control.control(bus,'ResumePreferred',interface,('org.mpris.MediaPlayer2.missing','missing')),'no eligible player')
    def test_toyota_array_selector_next_previous(self):
        layout=consumer_layout(DESCRIPTOR)
        self.assertEqual(pressed_usages(layout,b'\x03'),{0xb5})
        self.assertEqual(pressed_usages(layout,b'\x04'),{0xb6})
        self.assertEqual(pressed_usages(layout,b'\0'),set())
    def test_variable_media_bits_and_report_id(self):
        layout=consumer_layout(bytes.fromhex('050c85 02 09b5 09b6 7501 9502 8102'.replace(' ','')))
        self.assertEqual(pressed_usages(layout,b'\x02\x03'),{0xb5,0xb6})
        with self.assertRaises(ValueError):pressed_usages(layout,b'\x02')
    def test_held_key_only_fires_once_and_release_rearms(self):
        m=MediaKeys.__new__(MediaKeys);m.layouts={'2':consumer_layout(DESCRIPTOR)};m.pressed={};m.pending=queue.Queue()
        for data in (b'\x03',b'\x03',b'\0',b'\x03',b'\0',b'\x04'):
            self.assertTrue(m.command({'type':'hidSendReport','uuid':'2','hidReport':data}))
        self.assertEqual([m.pending.get_nowait() for _ in range(3)],['Next','Next','Previous'])
        self.assertTrue(m.pending.empty())
    def test_iap2_hid_component_keys_from_a_fiat_head_unit(self):
        # Descriptor and reports captured from a Fiat Scudo: Play, Pause, Next
        # and Previous as four one-bit fields followed by 28 padding bits.
        descriptor=bytes.fromhex('050c0901a101050c150025017501950409b009b109b509b68102751c95018101c0')
        m=MediaKeys.__new__(MediaKeys);m.layouts={};m.pressed={};m.pending=queue.Queue()
        self.assertFalse(m.iap_report(0x1238,bytes.fromhex('04000000')))
        m.iap_start(0x1238,descriptor)
        for report in ('04000000','04000000','00000000','08000000','00000000','01000000','00000000','02000000'):
            self.assertTrue(m.iap_report(0x1238,bytes.fromhex(report)))
        self.assertEqual([m.pending.get_nowait() for _ in range(4)],['Next','Previous','Play','Pause'])
        self.assertTrue(m.pending.empty())
        m.iap_stop(0x1238)
        self.assertFalse(m.iap_report(0x1238,bytes.fromhex('04000000')))
    def test_iap2_hid_component_without_media_keys_is_ignored(self):
        m=MediaKeys.__new__(MediaKeys);m.layouts={};m.pressed={};m.pending=queue.Queue()
        m.iap_start(7,bytes.fromhex('05010906a101c0'));m.iap_start(8,b'\x05')
        self.assertEqual(m.layouts,{})
    def test_pause_only_playing_and_does_not_launch_or_toggle(self):
        obj=Mock();player=Mock();bus=Mock();bus.list_names.return_value=['org.mpris.MediaPlayer2.test'];bus.get_object.return_value=obj
        state={'PlaybackStatus':'Playing','CanPause':True}
        props=SimpleNamespace(GetAll=lambda *a,**k:state)
        interface=lambda o,n:props if n=='org.freedesktop.DBus.Properties' else player
        self.assertIn('Pause delivered',control.control(bus,'PausePlaying',interface));player.Pause.assert_called_once();player.PlayPause.assert_not_called()
        player.reset_mock();state['PlaybackStatus']='Paused'
        self.assertEqual(control.control(bus,'PausePlaying',interface),'no eligible player');player.Pause.assert_not_called()
    def test_active_player_receives_next(self):
        bus=Mock();bus.list_names.return_value=['org.mpris.MediaPlayer2.old','org.mpris.MediaPlayer2.active'];bus.get_object.side_effect=lambda n,p:n
        players={n:Mock() for n in bus.list_names.return_value}
        def interface(obj,n):
            if n=='org.freedesktop.DBus.Properties':return SimpleNamespace(GetAll=lambda *a,**k:{'PlaybackStatus':'Playing' if obj.endswith('active') else 'Paused','CanGoNext':True})
            return players[obj]
        control.control(bus,'Next',interface)
        players['org.mpris.MediaPlayer2.active'].Next.assert_called_once();players['org.mpris.MediaPlayer2.old'].Next.assert_not_called()
