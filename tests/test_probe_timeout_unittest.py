import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('timeout_probe',
    Path(__file__).resolve().parents[1] / 'scripts' / 'wireless-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class HandshakeTimeoutTests(unittest.TestCase):
    def test_silent_continuous_channel_is_closed_for_retry(self):
        sock = Mock()
        with patch.object(probe.time, 'monotonic', side_effect=[0, 16, 16]), \
                self.assertLogs(level='ERROR') as logs:
            probe.probe(sock, threading.Event(), 0)
        sock.close.assert_called_once()
        sock.recv.assert_not_called()
        self.assertIn('iAP2 handshake timeout', '\n'.join(logs.output))

    def test_cancelled_worker_does_not_wait_for_deadline(self):
        stop = threading.Event()
        stop.set()
        sock = Mock()
        probe.probe(sock, stop, 0)
        sock.close.assert_called_once()
        sock.recv.assert_not_called()
