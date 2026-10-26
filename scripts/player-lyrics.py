#!/usr/bin/python3
"""Read timed lyrics without changing the player, its database, or network state."""
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path


def parse(text):
    if not isinstance(text, str) or len(text) > 262144:
        return []
    rows = []
    for line in text.splitlines():
        stamps = re.findall(r'\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]', line)
        if stamps:
            words = re.sub(r'\[[^]]*\]', '', line).strip()
            for minute, second, fraction in stamps:
                if int(second) < 60:
                    rows.append([int(minute)*60+int(second)+float('0.'+(fraction or '0')), words[:512]])
        else:
            # Mconnect caches decoded QRC/KRC timing, never encrypted payloads.
            stamp = re.search(r'\[(\d+),(\d+)\](.*)', line)
            if stamp:
                words = re.sub(r'\(\d+,\d+\)|<\d+,\d+,\d+>', '', stamp[3]).strip()
                rows.append([int(stamp[1])/1000, words[:512]])
        if len(rows) > 2048:
            return []
    return sorted(rows, key=lambda row: row[0])


def cached(track, database):
    if not database.is_file():
        return '', 0
    with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True, timeout=.1) as connection:
        # Match the exact platform/id hash published by Mconnect's MPRIS service.
        keys = connection.execute('select song_id,platform from lyrics_cache limit 10001').fetchall()
        if len(keys) > 10000:
            return '', 0
        for song, platform in keys:
            expected = '/org/mpris/MediaPlayer2/track/t'+hashlib.sha1((platform+':'+song).encode()).hexdigest()
            if track != expected:
                continue
            text, = connection.execute('select content from lyrics_cache where song_id=? and platform=?', (song,platform)).fetchone()
            offset = 0
            try:
                row = connection.execute('select offset_ms from lyrics_offsets where song_key=?', (platform+':'+song,)).fetchone()
                if row: offset = max(-60000,min(60000,int(row[0])))
            except sqlite3.Error:
                pass  # Older Mconnect schema has no per-track offsets.
            return text, offset
    return '', 0


def read(service, track):
    import dbus
    if not service.startswith('org.mpris.MediaPlayer2.') or not track.startswith('/'):
        return {'lines': [], 'offsetMs': 0}
    obj = dbus.SessionBus().get_object(service, '/org/mpris/MediaPlayer2')
    metadata = dbus.Interface(obj, 'org.freedesktop.DBus.Properties').Get('org.mpris.MediaPlayer2.Player', 'Metadata', timeout=1)
    if str(metadata.get('mpris:trackid', '')) != track:
        return {'lines': [], 'offsetMs': 0}
    text, offset = str(metadata.get('xesam:asText', '')), 0
    if not text and service == 'org.mpris.MediaPlayer2.harbour_mconnect':
        text, offset = cached(track, Path.home()/'.local/share/harbour-mconnect/mconnect.sqlite')
    return {'lines': parse(text), 'offsetMs': offset}


if __name__ == '__main__':
    try:
        result = read(*sys.argv[1:3])
    except Exception:
        result = {'lines': [], 'offsetMs': 0}
    print(json.dumps(result, ensure_ascii=False))
