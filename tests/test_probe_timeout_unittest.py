import importlib.util
import os
from pathlib import Path
import socket
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
        with patch.object(probe.time, 'monotonic', side_effect=[0, 0, 16, 16, 16, 16]), \
                self.assertLogs(level='ERROR') as logs:
            probe.probe(sock, threading.Event(), 0)
        sock.close.assert_called_once()
        sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        sock.recv.assert_not_called()
        self.assertIn('iAP2 handshake timeout', '\n'.join(logs.output))

    def test_cancelled_worker_does_not_wait_for_deadline(self):
        stop = threading.Event()
        stop.set()
        sock = Mock()
        probe.probe(sock, stop, 0)
        sock.close.assert_called_once()
        sock.recv.assert_not_called()

    def test_retired_bluetooth_channel_disconnects_the_peer_with_a_bluez_fd_copy(self):
        phone, car = socket.socketpair()
        bluez_copy = socket.socket(fileno=os.dup(phone.fileno()))
        car.settimeout(.5)
        stop = threading.Event()
        stop.set()
        try:
            probe.probe(phone, stop, 0)
            self.assertEqual(car.recv(1), b'')
        finally:
            phone.close()
            bluez_copy.close()
            car.close()

    def test_already_disconnected_channel_still_closes_its_descriptor(self):
        sock = Mock()
        sock.shutdown.side_effect = OSError('fixture disconnected channel')
        stop = threading.Event()
        stop.set()
        probe.probe(sock, stop, 0)
        sock.close.assert_called_once()

    def test_airplay_tunnel_keeps_its_own_close_semantics(self):
        sock = Mock()
        stop = threading.Event()
        stop.set()
        probe.probe(sock, stop, 0, transport='airplay')
        sock.shutdown.assert_not_called()
        sock.close.assert_called_once()
