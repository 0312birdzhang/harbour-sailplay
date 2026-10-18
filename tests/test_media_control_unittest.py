import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import queue
import unittest
from carplay_proto.mediakeys import consumer_layout,pressed_usages,MediaKeys
spec=importlib.util.spec_from_file_location('media_control',Path(__file__).resolve().parents[1]/'scripts/media-control.py')
control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
DESCRIPTOR=bytes.fromhex('050c0901a10115002506050c0a00000ab0000ab1000ab5000ab6000ab9000abc00750895018100c0')
class MediaTests(unittest.TestCase):
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
