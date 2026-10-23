"""Screen-only lifecycle; audio and the control/event session remain open."""
import os
import plistlib
import socket
import struct
import threading
import time
from .rtspclient import connect
from .videodemo import ScreenEncoder


class ScreenStream:
    def __init__(self, client, address, interface, shared, display, video, stream_id, width=1920, height=720, request_keyframe=None):
        self.width,self.height=width,height
        self.client, self.address, self.interface = client, address, interface
        self.shared, self.display = shared, display
        self.video = video
        self.desired_owner=1
        self.reopen_required=False
        self.encoder = ScreenEncoder(shared, stream_id)
        self.config = None
        self.need_idr = True
        self.last_keepalive = time.monotonic()
        self.lock = threading.RLock()
        self.request_keyframe = request_keyframe

    def _close_video(self):
        if self.video is not None:
            try:
                self.video.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.video.close()
            self.video = None

    def expect_owner(self,owner):
        # Called by the event thread: no I/O or control-socket requests here.
        self.desired_owner=owner
        if owner==2:self.reopen_required=True

    def ownership(self, owner):
        with self.lock:
            if owner == 2:
                self.desired_owner=2
                self.reopen_required=True
                if self.video is None:
                    return
                # Match the sender teardown order: stop TCP before TEARDOWN.
                self._close_video()
                payload = {'streams': [{'type': 110, 'uuid': self.display['uuid']}]}
                status, _, _ = self.client.request('TEARDOWN', '/',
                    plistlib.dumps(payload, fmt=plistlib.FMT_BINARY),
                    {'Content-Type': 'application/x-apple-binary-plist'})
                print('OEM screen-only TEARDOWN status={}'.format(status), flush=True)
                if status != 200:
                    raise RuntimeError('screen-only TEARDOWN rejected')
                return
            if self.video is not None and self.reopen_required:
                # A fast MODE round-trip may coalesce before the worker sees
                # the take. The old video TCP must still be retired.
                self._close_video()
                status,_,_=self.client.request('TEARDOWN','/',plistlib.dumps(
                    {'streams':[{'type':110,'uuid':self.display['uuid']}]},fmt=plistlib.FMT_BINARY),
                    {'Content-Type':'application/x-apple-binary-plist'})
                if status!=200:raise RuntimeError('stale screen teardown rejected')
            if self.video is not None:
                self.desired_owner=1
                return
            stream_id = int.from_bytes(os.urandom(7), 'big') or 1
            payload = {'streams': [{'type': 110, 'streamConnectionID': stream_id,
                        'latencyMs': 100, 'uuid': self.display['uuid']}]}
            status, _, body = self.client.request('SETUP', '/setup',
                plistlib.dumps(payload, fmt=plistlib.FMT_BINARY),
                {'Content-Type': 'application/x-apple-binary-plist'})
            print('CarPlay screen-only SETUP status={}'.format(status), flush=True)
            if status != 200:
                raise RuntimeError('screen resume SETUP rejected')
            stream = next(s for s in plistlib.loads(body)['streams'] if s['type'] == 110)
            self.video = connect(self.address, int(stream['dataPort']), self.interface).sock
            self.encoder = ScreenEncoder(self.shared, stream_id)
            self.config, self.need_idr = None, True
            status, _, _ = self.client.request('RECORD', '/')
            print('CarPlay screen resume RECORD status={}'.format(status), flush=True)
            if status != 200:
                self._close_video()
                raise RuntimeError('screen resume RECORD rejected')
            self.desired_owner=1
            self.reopen_required=False
            if self.request_keyframe:
                # A missing IDR must not end the session; the stream waits
                # for the next one either way.
                try:
                    self.request_keyframe()
                except Exception as error:
                    print('Keyframe request after screen resume failed: {}: {}'.format(
                        type(error).__name__, error), flush=True)

    def send(self, config, nals, timestamp):
        with self.lock:
            if self.video is None or self.desired_owner!=1:
                return False
            if self.need_idr and not any(n and n[0] & 31 == 5 for n in nals):
                return False
            if config != self.config:
                self.video.sendall(self.encoder.config(config, self.width, self.height, timestamp))
                self.config = config
            self.video.sendall(self.encoder.frame(nals, timestamp, self.width, self.height))
            if self.need_idr:
                print('Screen stream starts from IDR', flush=True)
                self.need_idr = False
            now = time.monotonic()
            if now - self.last_keepalive >= 1:
                self.video.sendall(struct.pack('<IB', 0, 2) + bytes(123))
                self.last_keepalive = now
            return True

    def close(self):
        with self.lock:
            self._close_video()
