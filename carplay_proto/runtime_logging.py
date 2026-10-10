"""Bounded private diagnostics independent of journald retention."""
import logging
import os
from logging.handlers import RotatingFileHandler


def private_handler(component, directory='/var/lib/sailplay/logs'):
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        path = os.path.join(directory, component + '.log')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        handler = RotatingFileHandler(path, maxBytes=4 * 1024 * 1024, backupCount=5)
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        return handler
    except OSError:
        logging.exception('private diagnostic log unavailable; using journal')


def configure(component):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    if os.geteuid() != 0:
        return
    handler = private_handler(component)
    if handler:
        logging.getLogger().addHandler(handler)
        logging.info('diagnostics start component=%s pid=%d boot=%s', component, os.getpid(), boot_id())


def boot_id():
    try:
        with open('/proc/sys/kernel/random/boot_id') as stream:
            return stream.read().strip()
    except OSError:
        return 'unknown'


class PersistentStream:
    """Tee existing line-oriented helper diagnostics into a bounded log."""
    def __init__(self, stream, handler):
        self.stream, self.handler, self.pending = stream, handler, ''

    def write(self, value):
        result = self.stream.write(value)
        self.pending += value
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            self.handler.handle(logging.LogRecord('handover', logging.INFO, '', 0,
                                                  line[:16384], (), None))
        if len(self.pending) > 16384:
            self.handler.handle(logging.LogRecord('handover', logging.INFO, '', 0,
                                                  self.pending[:16384], (), None))
            self.pending = ''
        return result

    def flush(self):
        self.stream.flush()
        self.handler.flush()


def persist_output(component):
    import sys
    if os.geteuid() != 0:
        return
    handler = private_handler(component)
    if handler:
        sys.stdout = PersistentStream(sys.stdout, handler)
        sys.stderr = sys.stdout
        print('diagnostics start component={} pid={} boot={}'.format(component, os.getpid(), boot_id()), flush=True)
