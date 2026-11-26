import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch
import unittest
spec=importlib.util.spec_from_file_location('player_queue',Path(__file__).parents[1]/'scripts/player-queue.py')
queue=importlib.util.module_from_spec(spec);spec.loader.exec_module(queue)

class QueueTests(unittest.TestCase):
    def test_system_queue_has_all_55_entries_and_current_index(self):
        api=Mock();api.snapshot.return_value=json.dumps({'ready':True,'index':12,
            'items':[{'uri':'file:///music/%d.mp3'%i,'title':'track %d'%i,'artist':'artist'} for i in range(55)]})
        result=queue.queue(Mock(),'org.mpris.MediaPlayer2.jolla-mediaplayer.instance1',lambda *a:api)
        self.assertEqual(len(result['items']),55);self.assertEqual(result['index'],12)
        self.assertEqual(result['items'][54]['index'],54)
        self.assertEqual(len(result['revision']),64)

    def test_mconnect_queue_uses_current_provider_song_identity(self):
        rows=[{'id':'1','platform':'local','title':'first'},{'id':'2','platform':'qq','title':'second'}]
        api=Mock();api.Request.side_effect=lambda method,*a,**k:json.dumps(rows if method=='queue' else {'song':rows[1]})
        result=queue.queue(Mock(),'org.mpris.MediaPlayer2.harbour_mconnect',lambda *a:api)
        self.assertEqual(result['index'],1);self.assertEqual(result['items'][1]['key'],'qq:2')

    def test_stale_queue_selection_is_rejected_before_playback(self):
        api=Mock();api.snapshot.return_value=json.dumps({'ready':True,'index':0,'items':[{'uri':'file:///new.mp3'}]})
        with self.assertRaises(ValueError):
            queue.play(Mock(),'org.mpris.MediaPlayer2.jolla-mediaplayer.instance1',0,'file:///old.mp3','old-revision',lambda *a:api)
        api.playIndex.assert_not_called()

    def test_sdk_provider_queue_maps_rows_and_current_index(self):
        rows=[{'id':'spotify:track:%d'%i,'title':'track %d'%i,'subtitle':'artist'} for i in range(3)]
        provider=('org.example.Player','/org/sailplay/v1/App')
        with patch.object(queue,'sdk_request',return_value={'queue':{'items':rows,'index':1}}) as request:
            result=queue.queue(Mock(),'org.mpris.MediaPlayer2.example',lambda *a:Mock(),provider)
        request.assert_called_once_with(provider,'queue.read',{})
        self.assertEqual(result['index'],1);self.assertEqual(result['items'][2]['key'],'spotify:track:2')
        self.assertEqual(result['items'][2]['artist'],'artist');self.assertEqual(len(result['revision']),64)

    def test_sdk_provider_queue_rejects_rows_without_identity(self):
        with patch.object(queue,'sdk_request',return_value={'queue':{'items':[{'title':'anonymous'}],'index':0}}):
            with self.assertRaises(ValueError):
                queue.queue(Mock(),'org.mpris.MediaPlayer2.example',lambda *a:Mock(),('org.example.Player','/org/sailplay/v1/App'))

    def test_sdk_provider_out_of_range_index_selects_nothing(self):
        with patch.object(queue,'sdk_request',return_value={'queue':{'items':[{'id':'a'}],'index':7}}):
            result=queue.queue(Mock(),'org.mpris.MediaPlayer2.example',lambda *a:Mock(),('org.example.Player','/org/sailplay/v1/App'))
        self.assertEqual(result['index'],-1)

    def test_sdk_provider_stale_selection_is_not_sent(self):
        with patch.object(queue,'sdk_request',return_value={'queue':{'items':[{'id':'new'}],'index':0}}) as request:
            with self.assertRaises(ValueError):
                queue.play(Mock(),'org.mpris.MediaPlayer2.example',0,'old','0'*64,lambda *a:Mock(),('org.example.Player','/org/sailplay/v1/App'))
        self.assertEqual([call.args[1] for call in request.call_args_list],['queue.read'])

    def test_player_without_provider_stays_unsupported(self):
        with self.assertRaises(ValueError):
            queue.queue(Mock(),'org.mpris.MediaPlayer2.example',lambda *a:Mock())
