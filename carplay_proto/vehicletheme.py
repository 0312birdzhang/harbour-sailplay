"""Session-owned car day/night state shared with the projected Qt renderers."""
import logging
import fcntl
import os
from pathlib import Path
import tempfile
import threading
import uuid


class VehicleTheme:
    def __init__(self, protocol, path='/run/sailplay-vehicle-theme/state.ini'):
        self.path = Path(path)
        self.protocol = protocol
        self.session = uuid.uuid4().hex
        self.lock = threading.Lock()
        self.content = None
        self.night = None
        self.owner = None

    def start(self):
        with self.lock:
            self.path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            # Both protocol entry points hold the projection session lease.
            descriptor = os.open(str(self.path.parent / 'session.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644)
            owner = os.fdopen(descriptor, 'r+b')
            try:
                fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                owner.seek(0)
                owner.write(self.session.encode())
                owner.truncate()
                owner.flush()
                os.fchmod(owner.fileno(), 0o644)
                self._write(None)
                self.owner = owner
            except Exception:
                owner.close()
                raise

    def update(self, night):
        if type(night) is not bool:
            raise ValueError('invalid vehicle night mode')
        with self.lock:
            if self.content is None or night == self.night or not self._owned():
                return
            self._write(night)
            logging.info('Vehicle theme protocol=%s night=%s', self.protocol, night)

    def command(self, value):
        if value.get('type') != 'setNightMode':
            return None
        self.update(value.get('params', {}).get('nightMode'))
        return {'status': 0}

    def _owned(self):
        try:
            return self.path.read_bytes() == self.content
        except FileNotFoundError:
            return False

    def _write(self, night):
        stat = Path('/proc/self/stat').read_text()
        start_time = stat[stat.rindex(')') + 2:].split()[19]
        value = 'unknown' if night is None else str(night).lower()
        content = ('[Vehicle]\nSession={}\nProtocol={}\nPID={}\nStartTime={}\nNightMode={}\n'.format(
            self.session, self.protocol, os.getpid(), start_time, value)).encode()
        descriptor, temporary = tempfile.mkstemp(prefix='.state-', dir=str(self.path.parent))
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(content)
                os.fchmod(stream.fileno(), 0o644)
            os.replace(temporary, self.path)
            self.content, self.night = content, night
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def close(self):
        with self.lock:
            try:
                if self.content is not None and self._owned():
                    self.path.unlink()
            finally:
                self.content = None
                if self.owner is not None:
                    self.owner.close()
                    self.owner = None
