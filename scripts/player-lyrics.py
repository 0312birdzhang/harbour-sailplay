#!/usr/bin/python3
"""Read timed lyrics without changing the player, its database, or network state."""
import hashlib
import json
import re
import sys
import base64
import math
import time
from pathlib import Path


def track_id(song):
    if not isinstance(song, dict) or not isinstance(song.get('id'), str) or not isinstance(song.get('platform'), str):
        return ''
    return '/org/mpris/MediaPlayer2/track/t'+hashlib.sha1((song['platform']+':'+song['id']).encode()).hexdigest()


def core_request(api, method, deadline):
    def request(name, arguments):
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('Mconnect lyrics read deadline')
        raw = str(api.Request(name, json.dumps(arguments), timeout=remaining))
        if len(raw) > 1048576: raise ValueError('oversized Mconnect response')
        return json.loads(raw)
    value = request(method, {})
    if isinstance(value, dict) and '_mconnectTransfer' in value:
        token, parts = value['_mconnectTransfer'], value.get('parts')
        if not isinstance(token, str) or len(token)>128 or type(parts) is not int or not 1<=parts<=43:
            raise ValueError('invalid Mconnect transfer')
        chunks = []
        for index in range(parts):
            part = request('_readTransfer', {'token': token, 'index': index})
            encoded = part.get('data', '')
            if not isinstance(encoded,str) or len(encoded)>32768: raise ValueError('invalid Mconnect part')
            chunks.append(base64.b64decode(encoded, validate=True))
        data = b''.join(chunks)
        if len(data)>1048576: raise ValueError('oversized Mconnect transfer')
        value = json.loads(data.decode('utf-8'))
    return value


def live_lyrics(api, track):
    """Use the same parsed document as Mconnect's phone UI, including local files.

    Validate the song on both sides of the read so a track transition cannot
    attach the previous song's lyrics to the new one.
    """
    deadline = time.monotonic()+1.8
    before = core_request(api, 'snapshot', deadline)
    if not isinstance(before,dict) or track_id(before.get('song')) != track: return None
    document = core_request(api, 'lyrics', deadline)
    after = core_request(api, 'snapshot', deadline)
    if not isinstance(after,dict) or track_id(after.get('song')) != track: return None
    if not isinstance(document,dict) or not isinstance(document.get('lines'),list) or len(document['lines'])>2048:
        return None
    lines = []
    for row in document['lines']:
        if not isinstance(row,dict) or not isinstance(row.get('text'),str):continue
        stamp = row.get('time')
        if isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or stamp<0:continue
        text = row['text'][:512]
        translation = row.get('translation')
        if isinstance(translation,str):
            translation = translation[:512]
            if translation.strip() and ' '.join(translation.split()) != ' '.join(text.split()):
                text+='\n'+translation
        if text.strip():lines.append([stamp/1000,text])
    if not lines:return None
    return {'lines':sorted(lines,key=lambda row:row[0]), 'offsetMs':0, 'plainText':'', 'source':'mconnect-core'}


def lyric_text(text):
    if isinstance(text,str) and text.startswith('mconnect-lyrics-v1\n'):
        try:
            value=json.loads(text.split('\n',1)[1])
            return value.get('content','') if isinstance(value,dict) and isinstance(value.get('content'),str) else ''
        except ValueError:return ''
    return text


def parse(text):
    text = lyric_text(text)
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
                words = re.sub(r'\(\d+,\d+(?:,\d+)?\)|<\d+,\d+,\d+>', '', stamp[3]).strip()
                rows.append([int(stamp[1])/1000, words[:512]])
        if len(rows) > 2048:
            return []
    return sorted(rows, key=lambda row: row[0])


def cached(track, database):
    if not database.is_file():
        return '', 0
    try:
        import sqlite3
    except ImportError:
        # Sailfish splits _sqlite3 out of python3-base. Live Core/MPRIS
        # lyrics remain available without this optional legacy cache reader.
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
    bus = dbus.SessionBus()
    obj = bus.get_object(service, '/org/mpris/MediaPlayer2')
    metadata = dbus.Interface(obj, 'org.freedesktop.DBus.Properties').Get('org.mpris.MediaPlayer2.Player', 'Metadata', timeout=1)
    if str(metadata.get('mpris:trackid', '')) != track:
        return {'lines': [], 'offsetMs': 0}
    if service == 'org.mpris.MediaPlayer2.harbour_mconnect':
        try:
            # Never activate another application merely to look for lyrics.
            owner = bus.get_name_owner('org.sailfishos.Mconnect.Core')
            api = dbus.Interface(bus.get_object(owner,'/org/sailfishos/Mconnect/Core'), 'org.sailfishos.Mconnect.Core')
            result = live_lyrics(api, track)
            if result is not None:return result
        except Exception:
            pass  # Older Mconnect releases still use the read-only cache path.
    text, offset = str(metadata.get('xesam:asText', '')), 0
    if not text and service == 'org.mpris.MediaPlayer2.harbour_mconnect':
        text, offset = cached(track, Path.home()/'.local/share/harbour-mconnect/mconnect.sqlite')
    text = lyric_text(text)
    lines = parse(text)
    return {'lines': lines, 'offsetMs': offset,
            'plainText': text[:16384] if not lines else ''}


if __name__ == '__main__':
    try:
        result = read(*sys.argv[1:3])
    except Exception:
        result = {'lines': [], 'offsetMs': 0}
    print(json.dumps(result, ensure_ascii=False))
