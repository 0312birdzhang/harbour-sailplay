"""Exclusive projection ownership shared by CarPlay and Android Auto."""
import configparser
import fcntl
import json
import os
import tempfile
import uuid


LOCK_PATH = '/run/sailplay-media.lock'
STATUS_PATH = '/run/sailplay-projection.ini'
SETTINGS_PATH = '/home/defaultuser/.config/sailplay/projection.ini'
PROTOCOLS = ('auto', 'carplay', 'android-auto')


class SessionBusy(RuntimeError):
    pass


def selected_protocol(path=SETTINGS_PATH):
    settings = configparser.ConfigParser()
    settings.read(path)
    protocol = settings.get('Projection', 'protocol', fallback='auto')
    if protocol not in PROTOCOLS:
        raise ValueError('invalid projection protocol setting')
    return protocol


def read_owner(descriptor):
    os.lseek(descriptor, 0, os.SEEK_SET)
    data = os.read(descriptor, 16385)
    if len(data) > 16384:
        raise ValueError('projection ownership record exceeds limit')
    if not data:
        return {}
    value = json.loads(data.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('invalid projection ownership record')
    return value


def current_owner(path=LOCK_PATH):
    try:
        descriptor = os.open(path + '.json', os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {}
    try:
        return read_owner(descriptor)
    finally:
        os.close(descriptor)


class SessionLease:
    def __init__(self, protocol, lock_path=LOCK_PATH, status_path=STATUS_PATH):
        self.protocol, self.lock_path, self.status_path = protocol, lock_path, status_path
        self.descriptor = None
        self.identity = uuid.uuid4().hex
        self.state = {}
        self.previous = {}

    def acquire(self, expected=None):
        """A restore job supplies the identity of the session that created it."""
        if self.descriptor is not None:
            raise RuntimeError('projection lease is already held')
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            if expected is not None:
                return False
            raise SessionBusy('another projection session owns Wi-Fi and media')
        try:
            previous = current_owner(self.lock_path)
            if expected is not None and previous.get('id') != expected:
                os.close(descriptor)
                return False
            self.descriptor = descriptor
            self.previous = previous
            if expected is not None:
                self.identity = expected
            self.state = dict(id=self.identity, protocol=self.protocol, pid=os.getpid(),
                              phase='connecting', network=previous.get('network'))
            self.save()
        except Exception:
            if self.descriptor is not None:
                self.descriptor = None
            os.close(descriptor)
            raise
        return True

    def save(self):
        if self.descriptor is None:
            raise RuntimeError('projection lease is not held')
        data = json.dumps(self.state, ensure_ascii=True).encode('utf-8')
        if len(data) > 16384:
            raise ValueError('projection ownership record exceeds limit')
        # Keep the lock inode stable and replace its journal atomically. A crash
        # during a write must leave the preceding network recovery plan readable.
        descriptor, temporary = tempfile.mkstemp(prefix='.sailplay-owner-',
                                                  dir=os.path.dirname(self.lock_path))
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.lock_path + '.json')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if self.status_path is not None:
            descriptor, temporary = tempfile.mkstemp(prefix='.sailplay-projection-',
                                                      dir=os.path.dirname(self.status_path))
            try:
                with os.fdopen(descriptor, 'w') as stream:
                    stream.write('[Projection]\nprotocol={}\nstate={}\n'.format(
                        self.protocol, self.state['phase']))
                    os.fchmod(stream.fileno(), 0o644)
                os.replace(temporary, self.status_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def update(self, **values):
        previous = self.state
        self.state = dict(previous, **values)
        try:
            self.save()
        except Exception:
            self.state = previous
            raise

    def phase(self, value):
        self.update(phase=value)

    def plan_network(self, old, target, forget=False, wifi_path=None, powered=True, debug=None):
        if old == target and wifi_path is None and not debug:
            return
        self.update(network=dict(old=old, target=target, forget=bool(forget),
                                 wifi_path=wifi_path, powered=bool(powered), debug=debug))

    def network_restored(self):
        self.update(network=None)

    def close(self):
        if self.descriptor is None:
            return
        try:
            self.phase('idle')
        finally:
            os.close(self.descriptor)
            self.descriptor = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, kind, value, traceback):
        self.close()
