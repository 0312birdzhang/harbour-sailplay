import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from android_auto.protobuf import field
from android_auto.transport import Packet, Transport


class AuthenticationTests(unittest.TestCase):
    def transport(self, packets):
        transport = Transport.__new__(Transport)
        transport.ready = False
        transport.tls = SimpleNamespace(do_handshake=Mock())
        transport.flush_handshake = Mock()
        transport.send_plain = Mock()
        transport.plain = Mock(side_effect=[Packet(0, 1, struct.pack('>HH', 1, 2))] + packets)
        return transport

    def test_authentication_accepts_zero_or_multiple_empty_tls_envelopes(self):
        for count in (0, 1, 3):
            with self.subTest(count=count):
                transport = self.transport([Packet(0, 3, b'')] * count + [Packet(0, 4, field(1, 0))])
                transport.handshake()
                self.assertTrue(transport.ready)

    def test_empty_tls_envelope_does_not_replace_authentication(self):
        for packet in (Packet(0, 4, field(1, -1)), Packet(0, 4, b''), Packet(0, 3, b'unexpected')):
            with self.subTest(packet=packet):
                transport = self.transport([Packet(0, 3, b''), packet])
                with self.assertRaises(ValueError):
                    transport.handshake()
                self.assertFalse(transport.ready)

    def test_excessive_empty_tls_envelopes_are_bounded(self):
        transport = self.transport([Packet(0, 3, b'')] * 128)
        with self.assertRaises(ValueError):
            transport.handshake()
        self.assertFalse(transport.ready)
