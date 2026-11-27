"""iAP2 NowPlayingUpdates (0x5000/0x5001/0x5002) encoder and MPRIS feeder."""
import json
import logging
import struct
import subprocess

from .body import Frame

START = 0x5000
UPDATE = 0x5001
STOP = 0x5002

STATUS_MAP = {'Stopped': 0, 'Playing': 1, 'Paused': 2}


def encode_param(param_id, payload):
    return struct.pack('>HH', len(payload) + 4, param_id) + payload


def _cstr(text):
    return str(text or '').replace('\x00', '').encode('utf-8')[:250] + b'\x00'


def encode_now_playing(snapshot):
    """Build an iAP2 NowPlayingUpdate (0x5001) control frame."""
    status = STATUS_MAP.get(snapshot.get('status', 'Stopped'), 0)
    duration_ms = max(0, min(0xffffffff, int(snapshot.get('durationMs', 0) or 0)))
    position_ms = max(0, min(0xffffffff, int(snapshot.get('positionMs', 0) or 0)))
    item_params = b''
    title = snapshot.get('title') or ''
    artist = snapshot.get('artist') or ''
    album = snapshot.get('album') or ''
    if title:
        item_params += encode_param(1, _cstr(title))
    if duration_ms:
        item_params += encode_param(4, struct.pack('>I', duration_ms))
    if album:
        item_params += encode_param(6, _cstr(album))
    if artist:
        item_params += encode_param(12, _cstr(artist))

    playback_params = encode_param(0, struct.pack('>B', status))
    if status != 0:
        playback_params += encode_param(1, struct.pack('>I', position_ms))
    app = snapshot.get('app') or ''
    if app:
        playback_params += encode_param(4, _cstr(app))

    body = b''
    if item_params:
        body += encode_param(0, item_params)
    body += encode_param(1, playback_params)
    return Frame(UPDATE, body)


class NowPlayingSubscription:
    def __init__(self):
        self.subscribed = False

    def handle(self, frame):
        if frame.message_id == START:
            self.subscribed = True
            return True
        if frame.message_id == STOP:
            self.subscribed = False
            return True
        return False


class NowPlayingFeed:
    def poll(self):
        try:
            result = subprocess.run(
                ['su', 'defaultuser', '-s', '/bin/sh', '-c',
                 'exec env XDG_RUNTIME_DIR=/run/user/100000 '
                 'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket '
                 'python3 /opt/sailplay/scripts/media-control.py NowPlaying'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1.5, universal_newlines=True)
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout.strip())
        except Exception:
            logging.debug('NowPlaying MPRIS poll failed', exc_info=True)
        return None


class NowPlayingSender:
    def __init__(self):
        self.last_meta = None
        self.last_position_ms = -1

    def reset(self):
        self.last_meta = None
        self.last_position_ms = -1

    def frames(self, snapshot, subscription, received_messages):
        if not subscription.subscribed or (received_messages and UPDATE not in received_messages):
            self.reset()
            return []
        if not snapshot:
            return []
        meta = (
            snapshot.get('status', 'Stopped'),
            snapshot.get('title', ''),
            snapshot.get('artist', ''),
            snapshot.get('album', ''),
            int(snapshot.get('durationMs', 0) or 0),
            snapshot.get('app', ''),
        )
        pos = int(snapshot.get('positionMs', 0) or 0)
        if meta == self.last_meta:
            if meta[0] != 'Playing' or abs(pos - self.last_position_ms) < 5000:
                return []
        self.last_meta = meta
        self.last_position_ms = pos
        return [encode_now_playing(snapshot)]
