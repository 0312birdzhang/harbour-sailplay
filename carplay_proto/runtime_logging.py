"""Opt-in, bounded private diagnostics independent of journald retention."""
import atexit
import codecs
import configparser
import datetime
import fcntl
import functools
import logging
import os
import re
import select
import sys
import threading
import time
from collections import OrderedDict

SETTINGS_PATH = '/home/defaultuser/.config/sailplay/diagnostics.ini'
LOG_DIRECTORY = '/var/lib/sailplay/logs'
MAX_BYTES = 4 * 1024 * 1024
BACKUP_COUNT = 5
MAX_LINE = 16384


def socket_endpoint(sock, method):
    try:
        return getattr(sock, method)()
    except (OSError, AttributeError):
        return 'unavailable'


class RepeatGate:
    """Bound a diagnostic line that another process can make repeat forever.

    The first ``burst`` events of a kind in each ``window`` seconds pass. The
    rest are counted, and the count is handed to the next event that passes,
    so the log still says how often the event happened.
    """
    def __init__(self, burst=6, window=60, limit=64, clock=time.monotonic):
        self.burst, self.window, self.limit, self.clock = burst, window, limit, clock
        self.kinds = OrderedDict()

    def admit(self, kind):
        """Return None to drop the event, else how many were dropped before it."""
        now = self.clock()
        start, passed, dropped = self.kinds.pop(kind, (now, 0, 0))
        if now - start >= self.window:
            start, passed = now, 0
        if passed >= self.burst:
            self.kinds[kind] = (start, passed, dropped + 1)
            return None
        self.kinds[kind] = (start, passed + 1, 0)
        while len(self.kinds) > self.limit:
            self.kinds.popitem(last=False)
        return dropped


class _Settings:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.next_check = 0
        self.stamp = None
        self.enabled = False

    def read(self, refresh=False):
        with self.lock:
            now = time.monotonic()
            if not refresh and now < self.next_check:
                return self.enabled
            self.next_check = now + 0.25
            try:
                info = os.stat(self.path)
                stamp = (info.st_ino, info.st_mtime_ns, info.st_size)
                if stamp != self.stamp or refresh:
                    settings = configparser.RawConfigParser()
                    with open(self.path, encoding='utf-8') as source:
                        settings.read_file(source)
                    self.enabled = settings.getboolean('Diagnostics', 'enabled', fallback=False)
                    self.stamp = stamp
            except (OSError, ValueError, configparser.Error):
                self.stamp = None
                self.enabled = False
            return self.enabled


@functools.lru_cache(maxsize=32)
def _settings(path):
    return _Settings(path)


def collection_enabled(settings_path=None, refresh=False):
    path = settings_path or os.environ.get('SAILPLAY_DIAGNOSTICS_CONFIG', SETTINGS_PATH)
    return _settings(path).read(refresh)


class _DiagnosticFormat(logging.Formatter):
    def __init__(self, component):
        super().__init__('%(message)s')
        self.component = component

    def format(self, record):
        wall = datetime.datetime.fromtimestamp(record.created).astimezone().isoformat(timespec='milliseconds')
        message = super().format(record).replace('\r', '\\r').replace('\n', '\\n')
        source_pid = getattr(record, 'source_pid', record.process)
        return '{} mono={:.6f} pid={} sourcePid={} thread={} component={} {} {}'.format(
            wall, time.monotonic(), record.process, source_pid, record.threadName,
            self.component, record.levelname, message)


class PrivateRotatingHandler(logging.Handler):
    """Open under a process-shared lock for each append, including rotation.

    Independent handover workers can use the same component safely. No open
    log descriptor survives rotation in another worker or a setting change.
    """
    def __init__(self, component, path, settings_path=None, private_directory=True):
        super().__init__()
        self.component = component
        self.baseFilename = os.path.abspath(path)
        self.settings_path = settings_path
        self.private_directory = private_directory
        self.maxBytes = MAX_BYTES
        self.backupCount = BACKUP_COUNT
        self.active = False
        self.last_sync = 0
        self.last_error = float('-inf')
        self.setFormatter(_DiagnosticFormat(component))

    def is_enabled(self):
        return collection_enabled(self.settings_path)

    def _rotate(self):
        if self.backupCount <= 0:
            os.unlink(self.baseFilename)
            return
        oldest = self.baseFilename + '.' + str(self.backupCount)
        if os.path.lexists(oldest):
            os.unlink(oldest)
        for index in range(self.backupCount - 1, 0, -1):
            source = self.baseFilename + '.' + str(index)
            if os.path.lexists(source):
                os.replace(source, self.baseFilename + '.' + str(index + 1))
        os.replace(self.baseFilename, self.baseFilename + '.1')

    def _append(self, record):
        data = (self.format(record) + '\n').encode('utf-8', 'replace')
        limit = min(MAX_LINE, self.maxBytes)
        if len(data) > limit:
            marker = b' [truncated]\n'
            data = data[:max(0, limit - len(marker))].decode('utf-8', 'ignore').encode('utf-8') + marker[:limit]
        directory = os.path.dirname(self.baseFilename)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if self.private_directory:
            os.chmod(directory, 0o700)
        flags = os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        lock_fd = os.open(self.baseFilename + '.lock', flags | os.O_RDWR, 0o600)
        fd = None
        try:
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            fd = os.open(self.baseFilename, flags | os.O_WRONLY | os.O_APPEND, 0o600)
            os.fchmod(fd, 0o600)
            size = os.fstat(fd).st_size
            if size and size + len(data) > self.maxBytes:
                os.close(fd)
                fd = None
                self._rotate()
                fd = os.open(self.baseFilename, flags | os.O_WRONLY | os.O_APPEND, 0o600)
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'ab') as output:
                fd = None
                output.write(data)
                output.flush()
                now = time.monotonic()
                if record.levelno >= logging.ERROR or now - self.last_sync >= 1:
                    os.fsync(output.fileno())
                    self.last_sync = now
        finally:
            if fd is not None:
                os.close(fd)
            os.close(lock_fd)

    def emit(self, record):
        if self._closed:
            return
        if not self.is_enabled():
            self.active = False
            return
        try:
            if not self.active:
                start = logging.LogRecord(self.component, logging.INFO, '', 0,
                    'diagnostics enabled boot={} version={}'.format(boot_id(), package_version()), (), None)
                self._append(start)
                self.active = True
            self._append(record)
        except (OSError, ValueError) as error:
            # Bypass redirected stderr so an unavailable disk cannot recurse.
            now = time.monotonic()
            if now - self.last_error >= 60:
                self.last_error = now
                sys.__stderr__.write('Sailplay diagnostic write failed component={} error={}\n'.format(
                    self.component, type(error).__name__))


def private_handler(component, directory=LOG_DIRECTORY, settings_path=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', component):
        raise ValueError('invalid diagnostic component name')
    return PrivateRotatingHandler(component, os.path.join(directory, component + '.log'), settings_path)


def configure(component):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    if os.geteuid() != 0:
        return
    handler = private_handler(component)
    logging.getLogger().addHandler(handler)
    # basicConfig's console handler retains the original stderr. Print calls
    # and uncaught tracebacks are also persisted without duplicating records.
    sys.stdout = PersistentStream(sys.stdout, handler)
    sys.stderr = PersistentStream(sys.stderr, handler)
    atexit.register(sys.stdout.flush_all)
    atexit.register(sys.stderr.flush_all)
    logging.info('process started component=%s pid=%d boot=%s version=%s',
                 component, os.getpid(), boot_id(), package_version())


def boot_id():
    try:
        with open('/proc/sys/kernel/random/boot_id') as stream:
            return stream.read().strip()
    except OSError:
        return 'unknown'


def package_version():
    try:
        with open('/opt/sailplay/version') as source:
            return source.read(128).strip()
    except OSError:
        return 'unknown'


class PersistentStream:
    """Tee existing line-oriented helper diagnostics into a bounded log."""
    def __init__(self, stream, handler, source_pid=None):
        self.stream, self.handler = stream, handler
        self.source_pid = source_pid
        self.lock = threading.RLock()
        self.pending = OrderedDict()

    def _line(self, value, thread=None):
        record = logging.LogRecord(self.handler.component, logging.INFO, '', 0, value[:MAX_LINE], (), None)
        if thread is not None:
            record.thread, record.threadName = thread.ident, thread.name
        if self.source_pid is not None:
            record.source_pid = self.source_pid
        self.handler.handle(record)

    def write(self, value):
        with self.lock:
            result = self.stream.write(value)
            if not self.handler.is_enabled():
                self.pending.clear()
                return result
            thread = threading.current_thread()
            pending = self.pending.pop(thread, '') + value
            while '\n' in pending:
                line, pending = pending.split('\n', 1)
                self._line(line)
            if len(pending) > MAX_LINE:
                self._line(pending[:MAX_LINE] + ' [truncated]')
                pending = ''
            if pending:
                self.pending[thread] = pending
            if len(self.pending) > 64:
                _, partial = self.pending.popitem(last=False)
                self._line(partial)
            return result

    def flush(self):
        with self.lock:
            self.stream.flush()
            partial = self.pending.pop(threading.current_thread(), '')
            if partial:
                self._line(partial)
            self.handler.flush()

    def flush_all(self):
        with self.lock:
            getattr(self.stream, 'flush_all', self.stream.flush)()
            for thread, partial in self.pending.items():
                self._line(partial, thread)
            self.pending.clear()
            self.handler.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


class ProcessOutput:
    """Drain a child's diagnostics even while collection is disabled."""
    def __init__(self, component, stream, source_pid=None, handler=None):
        self.stream = stream
        self.handler = handler or private_handler(component)
        self.source_pid = source_pid
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name='output-' + component, daemon=True)
        self.thread.start()

    def run(self):
        import io
        output = PersistentStream(io.StringIO(), self.handler, self.source_pid)
        # The child console stream is discarded after each block. Retaining it
        # in StringIO across blocks would grow even with collection disabled.
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        try:
            while not self.stop.is_set():
                ready, _, _ = select.select([self.stream], [], [], 0.2)
                if not ready:
                    continue
                data = os.read(self.stream.fileno(), 8192)
                if not data:
                    break
                output.write(decoder.decode(data))
                output.stream.seek(0)
                output.stream.truncate(0)
            output.write(decoder.decode(b'', final=True))
            output.flush()
        except (OSError, ValueError):
            return

    def close(self):
        self.thread.join(1)
        self.stop.set()
        self.thread.join(1)
        self.stream.close()
        self.handler.close()


class _TunnelPrefix(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        return 'iAP tunnel: ' + text if record.threadName.startswith('iAP tunnel') else text


def log_to_stdout():
    """Send logging records to (persisted) stdout at INFO.

    Without this, the first logging call in a print-based helper installs a
    WARNING-level stderr handler and every later logging.info is dropped.
    """
    import sys
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_TunnelPrefix('%(message)s'))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def persist_output(component, log_file=None):
    import sys
    if os.geteuid() != 0 and not log_file:
        return
    if log_file:
        # Keep an older explicit log-file symlink pointed at its existing file.
        # No new per-session files or links are created.
        path = os.path.realpath(log_file)
        handler = PrivateRotatingHandler(component, path, private_directory=False)
        sys.stdout = PersistentStream(sys.stdout, handler)
    if os.geteuid() == 0:
        sys.stdout = PersistentStream(sys.stdout, private_handler(component))
    sys.stderr = sys.stdout
    atexit.register(sys.stdout.flush_all)
    print('process started component={} pid={} boot={} version={}'.format(
        component, os.getpid(), boot_id(), package_version()), flush=True)
