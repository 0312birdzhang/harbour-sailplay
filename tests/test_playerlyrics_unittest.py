import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
import json
import base64
spec=importlib.util.spec_from_file_location('lyrics',Path(__file__).parents[1]/'scripts/player-lyrics.py')
lyrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(lyrics)

class LyricsTests(unittest.TestCase):
    def test_identical_translation_is_hidden_without_removing_repeated_verses(self):
        song={'platform':'local','id':'/music/repeated.mp3'}
        class Api:
            def Request(self,method,args,**kwargs):
                return json.dumps({'song':song} if method=='snapshot' else {'lines':[
                    {'time':1000,'text':'same line','translation':'same line'},
                    {'time':2000,'text':'same line','translation':'  same   line  '},
                    {'time':3000,'text':'original','translation':'different translation'}]})
        self.assertEqual(lyrics.live_lyrics(Api(),lyrics.track_id(song))['lines'],[
            [1.0,'same line'],[2.0,'same line'],[3.0,'original\ndifferent translation']])

    def test_live_local_lyrics_match_phone_document_and_units(self):
        song={'platform':'local','id':'/music/offline.mp3'}
        class Api:
            def Request(self,method,args,**kwargs):
                return json.dumps({'song':song} if method=='snapshot' else
                    {'loading':False,'lines':[{'time':15000,'text':'local line','translation':'translated'}]})
        result=lyrics.live_lyrics(Api(),lyrics.track_id(song))
        self.assertEqual(result['lines'],[[15.0,'local line\ntranslated']])
        self.assertEqual(result['source'],'mconnect-core')

    def test_live_track_change_discards_previous_lyrics(self):
        song={'platform':'local','id':'/music/first.mp3'}
        class Api:
            snapshots=0
            def Request(self,method,args,**kwargs):
                if method=='lyrics':return json.dumps({'lines':[{'time':0,'text':'wrong song'}]})
                self.snapshots+=1
                return json.dumps({'song':song if self.snapshots==1 else {'platform':'local','id':'/music/next.mp3'}})
        self.assertIsNone(lyrics.live_lyrics(Api(),lyrics.track_id(song)))

    def test_chunked_live_response_and_invalid_rows(self):
        song={'platform':'netease','id':'42'}
        data=json.dumps({'lines':[{'time':2000,'text':'valid'},{'time':-1,'text':'invalid'},
                                  {'time':'bad','text':'invalid'}]}).encode()
        class Api:
            def Request(self,method,args,**kwargs):
                if method=='snapshot':return json.dumps({'song':song})
                if method=='lyrics':return json.dumps({'_mconnectTransfer':'test-token','parts':1})
                return json.dumps({'data':base64.b64encode(data).decode()})
        self.assertEqual(lyrics.live_lyrics(Api(),lyrics.track_id(song))['lines'],[[2.0,'valid']])

    def test_cache_envelope_is_decoded(self):
        content='mconnect-lyrics-v1\n'+json.dumps({'content':'[00:01]cached','source':'lrclib'})
        self.assertEqual(lyrics.parse(content),[[1.0,'cached']])
    def test_timing_and_multiple_stamps(self):
        self.assertEqual(lyrics.parse('[00:12.50][01:20]hello\n[00:13.001]next'), [[12.5,'hello'],[13.001,'next'],[80.0,'hello']])
    def test_word_timing_and_bounds(self):
        self.assertEqual(lyrics.parse('[1200,300]one(1200,150)two(1350,150)'), [[1.2,'onetwo']])
        self.assertEqual(lyrics.parse('[1200,300]<0,150,0>one<150,150,0>two'), [[1.2,'onetwo']])
        self.assertEqual(lyrics.parse('[1200,300](1200,150,0)one(1350,150,0)two'), [[1.2,'onetwo']])
        self.assertEqual(lyrics.parse('x'*262145), [])
        self.assertEqual(lyrics.parse('[00:99]bad'), [])
    def test_cache_exact_identity_and_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cache.sqlite';c=sqlite3.connect(str(p))
            c.execute('create table lyrics_cache(song_id text,platform text,content text)')
            c.execute('insert into lyrics_cache values(?,?,?)',('42','qq','[00:01]line'))
            c.commit();c.close();before=p.read_bytes()
            track='/org/mpris/MediaPlayer2/track/t'+hashlib.sha1(b'qq:42').hexdigest()
            self.assertEqual(lyrics.cached(track,p),('[00:01]line',0))
            self.assertEqual(lyrics.cached('/wrong',p),('',0))
            self.assertEqual(before,p.read_bytes())
