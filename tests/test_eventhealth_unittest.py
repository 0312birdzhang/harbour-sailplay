import threading
import unittest
from types import SimpleNamespace
from carplay_proto.videodemo import DemoEvents


class EventHealthTests(unittest.TestCase):
    def test_eof_marks_event_channel_dead(self):
        events = DemoEvents.__new__(DemoEvents)
        events.stop = threading.Event()
        events.sock = SimpleNamespace(recv=lambda size: b'')
        events.run()
        self.assertTrue(events.stop.is_set())

    def test_socket_failure_marks_event_channel_dead(self):
        events = DemoEvents.__new__(DemoEvents)
        events.stop = threading.Event()
        def receive(size):
            raise ConnectionResetError('reset')
        events.sock = SimpleNamespace(recv=receive)
        events.run()
        self.assertTrue(events.stop.is_set())
