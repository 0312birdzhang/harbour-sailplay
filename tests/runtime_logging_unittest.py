import io
import logging
import multiprocessing
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from carplay_proto.runtime_logging import (PersistentStream, ProcessOutput, RepeatGate, collection_enabled,
                                          configure, persist_output, private_handler, socket_endpoint)


def concurrent_writer(directory, settings, worker):
    handler = private_handler('shared', directory, settings)
    handler.maxBytes = 1024
    handler.backupCount = 64
    for event in range(35):
        handler.handle(logging.LogRecord('shared', logging.INFO, '', 0,
            'worker={} event={}'.format(worker, event), (), None))
    handler.close()


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings = str(Path(self.temporary.name) / 'diagnostics.ini')
        self.directory = str(Path(self.temporary.name) / 'logs')

    def set_enabled(self, enabled):
        Path(self.settings).write_text('[Diagnostics]\nenabled={}\n'.format(str(enabled).lower()))
        collection_enabled(self.settings, refresh=True)

    def handler(self, component='session'):
        return private_handler(component, self.directory, self.settings)

    def log_content(self, component='session'):
        return ''.join(path.read_text() for path in Path(self.directory).glob(component + '.log*')
                       if not path.name.endswith('.lock'))

    def test_default_off_creates_no_directory_and_keeps_console(self):
        handler = self.handler()
        original = io.StringIO()
        output = PersistentStream(original, handler)
        output.write('off by default\n')
        output.flush()
        handler.close()
        self.assertEqual(original.getvalue(), 'off by default\n')
        self.assertFalse(Path(self.directory).exists())

    def test_live_enable_disable_and_no_retroactive_partial_lines(self):
        handler = self.handler()
        output = PersistentStream(io.StringIO(), handler)
        output.write('private while off')
        self.set_enabled(True)
        output.write('enabled line\n')
        output.write('pending before disable')
        self.set_enabled(False)
        before = self.log_content()
        output.write('disabled line\n')
        output.flush()
        self.assertEqual(self.log_content(), before)
        self.set_enabled(True)
        output.write('re-enabled line\n')
        handler.close()
        content = self.log_content()
        self.assertIn('enabled line', content)
        self.assertIn('re-enabled line', content)
        self.assertNotIn('private while off', content)
        self.assertNotIn('pending before disable', content)
        self.assertNotIn('disabled line', content)

    def test_invalid_and_deleted_settings_disable_collection(self):
        self.set_enabled(True)
        self.assertTrue(collection_enabled(self.settings))
        Path(self.settings).write_text('[Diagnostics]\nenabled=malformed\n')
        self.assertFalse(collection_enabled(self.settings, refresh=True))
        Path(self.settings).unlink()
        self.assertFalse(collection_enabled(self.settings, refresh=True))

    def test_restart_keeps_existing_lines_and_private_permissions(self):
        self.set_enabled(True)
        for line in ('first boot\n', 'second boot\n'):
            handler = self.handler()
            output = PersistentStream(io.StringIO(), handler)
            output.write(line)
            output.flush()
            handler.close()
        content = self.log_content()
        self.assertIn('first boot', content)
        self.assertIn('second boot', content)
        self.assertRegex(content, r'\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d mono=\d+\.\d+ pid=\d+')
        self.assertIn('thread=MainThread component=session INFO', content)
        self.assertEqual(os.stat(self.directory).st_mode & 0o777, 0o700)
        for path in Path(self.directory).iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_partial_lines_and_bounded_rotation(self):
        self.set_enabled(True)
        handler = self.handler('wifi')
        handler.maxBytes = 512
        handler.backupCount = 2
        original = io.StringIO()
        output = PersistentStream(original, handler)
        output.write('partial')
        output.write(' line\n')
        for i in range(20):
            output.write('event {} {}\n'.format(i, 'x' * 40))
        output.flush()
        handler.close()
        self.assertTrue(original.getvalue().startswith('partial line\n'))
        logs = [path for path in Path(self.directory).iterdir() if not path.name.endswith('.lock')]
        self.assertEqual(len(logs), 3)
        self.assertTrue(all(path.stat().st_size <= 512 for path in logs))
        self.assertIn('event 19', (Path(self.directory) / 'wifi.log').read_text())

    def test_long_lines_and_flush_are_bounded(self):
        self.set_enabled(True)
        handler = self.handler()
        output = PersistentStream(io.StringIO(), handler)
        output.write('x' * 100000)
        self.assertFalse(output.pending)
        output.write('EOF partial')
        output.flush()
        content = self.log_content()
        self.assertIn('EOF partial', content)
        self.assertTrue(all(len(line.encode()) < 16384 for line in content.splitlines()))
        handler.close()

    def test_thread_fragments_are_not_merged(self):
        self.set_enabled(True)
        handler = self.handler()
        output = PersistentStream(io.StringIO(), handler)
        barrier = threading.Barrier(2)
        def write(name):
            output.write(name)
            barrier.wait(2)
            output.write(' complete\n')
        threads = [threading.Thread(target=write, args=(name,), name=name) for name in ('alpha', 'beta')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        content = self.log_content()
        self.assertIn('thread=alpha component=session INFO alpha complete', content)
        self.assertIn('thread=beta component=session INFO beta complete', content)
        handler.close()

    def test_shutdown_flush_keeps_partial_line_thread_identity(self):
        self.set_enabled(True)
        handler = self.handler()
        output = PersistentStream(io.StringIO(), handler)
        writer = threading.Thread(target=lambda: output.write('partial worker line'), name='worker')
        writer.start()
        writer.join(2)
        output.flush_all()
        self.assertIn('thread=worker component=session INFO partial worker line', self.log_content())
        handler.close()

    def test_diagnostics_can_read_a_socket_that_has_already_closed(self):
        sock = socket.socket()
        sock.close()
        self.assertEqual(socket_endpoint(sock, 'getpeername'), 'unavailable')

    def test_explicit_legacy_symlink_is_bounded_without_chmod_of_parent(self):
        self.set_enabled(True)
        parent = Path(self.temporary.name)
        parent.chmod(0o755)
        target = parent / 'old.log.123'
        target.write_text('historical event\n')
        link = parent / 'old.log'
        link.symlink_to(target.name)
        with patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()), \
                patch('carplay_proto.runtime_logging.os.geteuid', return_value=100000), \
                patch.dict(os.environ, {'SAILPLAY_DIAGNOSTICS_CONFIG': self.settings}):
            persist_output('explicit', str(link))
            print('explicit event', flush=True)
        self.assertEqual(parent.stat().st_mode & 0o777, 0o755)
        self.assertTrue(link.is_symlink())
        self.assertIn('historical event', target.read_text())
        self.assertIn('explicit event', target.read_text())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertFalse(Path(self.directory).exists())

    def test_concurrent_rotation_keeps_every_retained_record_once(self):
        self.set_enabled(True)
        context = multiprocessing.get_context('fork')
        workers = [context.Process(target=concurrent_writer, args=(self.directory, self.settings, worker))
                   for worker in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        content = self.log_content('shared')
        for worker in range(4):
            for event in range(35):
                self.assertEqual(content.count('worker={} event={}\n'.format(worker, event)), 1)
        self.assertTrue(all(path.stat().st_size <= 1024 for path in Path(self.directory).glob('shared.log*')))

    def test_child_pipe_is_drained_while_disabled_and_partial_eof_is_saved(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.set_enabled(enabled)
                read_fd, write_fd = os.pipe()
                collector = ProcessOutput('child', os.fdopen(read_fd, 'rb', buffering=0), 123, self.handler('child'))
                try:
                    for _ in range(20):
                        os.write(write_fd, b'child event\n' * 500)
                    os.write(write_fd, b'partial EOF')
                finally:
                    os.close(write_fd)
                    collector.close()
                self.assertFalse(collector.thread.is_alive())
                if enabled:
                    content = self.log_content('child')
                    self.assertIn('sourcePid=123', content)
                    self.assertIn('partial EOF', content)
                else:
                    self.assertFalse(Path(self.directory).exists())

    def test_configure_captures_prints_and_errors_without_duplicate_records(self):
        self.set_enabled(True)
        handler = self.handler()
        root = logging.getLogger()
        original_handlers, original_level = root.handlers[:], root.level
        root.handlers = []
        try:
            with patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()), \
                    patch('carplay_proto.runtime_logging.os.geteuid', return_value=0), \
                    patch('carplay_proto.runtime_logging.private_handler', return_value=handler):
                configure('session')
                print('print evidence', flush=True)
                logging.error('error evidence')
                import sys
                sys.stderr.write('traceback evidence\n')
                content = self.log_content()
                self.assertEqual(content.count('print evidence'), 1)
                self.assertEqual(content.count('error evidence'), 1)
                self.assertEqual(content.count('traceback evidence'), 1)
        finally:
            for current in root.handlers:
                current.close()
            root.handlers, root.level = original_handlers, original_level


class RepeatGateTests(unittest.TestCase):
    def test_burst_passes_then_repeats_are_counted_until_the_window_ends(self):
        now = [100.0]
        gate = RepeatGate(burst=2, window=60, clock=lambda: now[0])
        self.assertEqual([gate.admit('a'), gate.admit('a')], [0, 0])
        self.assertEqual([gate.admit('a') for _ in range(5)], [None] * 5)
        self.assertEqual(gate.admit('b'), 0)
        now[0] += 60
        self.assertEqual(gate.admit('a'), 5)
        self.assertEqual(gate.admit('a'), 0)
        self.assertIsNone(gate.admit('a'))

    def test_kinds_are_bounded(self):
        gate = RepeatGate(limit=4, clock=lambda: 0.0)
        for kind in range(50):
            gate.admit(kind)
        self.assertEqual(len(gate.kinds), 4)


if __name__ == '__main__':
    unittest.main()
