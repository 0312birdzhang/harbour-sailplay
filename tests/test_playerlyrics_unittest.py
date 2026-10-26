import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('lyrics',Path(__file__).parents[1]/'scripts/player-lyrics.py')
lyrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(lyrics)

class LyricsTests(unittest.TestCase):
    def test_timing_and_multiple_stamps(self):
        self.assertEqual(lyrics.parse('[00:12.50][01:20]hello\n[00:13.001]next'), [[12.5,'hello'],[13.001,'next'],[80.0,'hello']])
    def test_word_timing_and_bounds(self):
        self.assertEqual(lyrics.parse('[1200,300]one(1200,150)two(1350,150)'), [[1.2,'onetwo']])
        self.assertEqual(lyrics.parse('[1200,300]<0,150,0>one<150,150,0>two'), [[1.2,'onetwo']])
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
