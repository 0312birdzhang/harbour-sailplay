import unittest
from carplay_proto.iap2link import (ACK, DETECT, SYN, Decoder, Packet, encode,
                                   parse_synchronization, synchronization)


class LinkTests(unittest.TestCase):
    def test_ack_reference_bytes(self):
        self.assertEqual(encode(Packet(ACK, 0, 0, 0, None)),
                         bytes.fromhex('ff5a0009400000005e'))

    def test_detection_and_fragmented_syn(self):
        packet = Packet(SYN, 0, 0, 0, synchronization())
        decoder = Decoder()
        actual = []
        for value in DETECT + encode(packet):
            actual += decoder.feed(bytes([value]))
        self.assertEqual(actual, [DETECT, packet])

    def test_corruption_not_delivered(self):
        packet = Packet(ACK, 255, 0, 10, b'@@test')
        bad = bytearray(encode(packet))
        bad[-1] ^= 1
        decoder = Decoder()
        self.assertEqual(decoder.feed(bad + encode(packet)), [packet])
        self.assertEqual(decoder.errors, 1)

    def test_header_resynchronization(self):
        packet = Packet(ACK, 0, 255, 0, None)
        decoder = Decoder()
        self.assertEqual(decoder.feed(bytes.fromhex('ff5a00004000000000') +
                                      encode(packet)), [packet])

    def test_maximum_packet_chunking(self):
        packet = Packet(ACK, 1, 0, 10, b'x' * 65525)
        decoder = Decoder()
        raw = encode(packet)
        self.assertEqual(len(raw), 65535)
        self.assertEqual(decoder.feed(raw[:-1]), [])
        self.assertEqual(decoder.feed(raw[-1:]), [packet])
        self.assertEqual(len(decoder.buffer), 0)
        with self.assertRaises(ValueError):
            encode(packet._replace(payload=b'x' * 65526))

    def test_sync_descriptors(self):
        limits, sessions = parse_synchronization(synchronization())
        self.assertEqual(limits, (1, 1, 4096, 1000, 100, 5, 1))
        self.assertEqual(sessions, [(10, 0, 1)])
        with self.assertRaises(ValueError):
            parse_synchronization(synchronization() + b'\x00')


if __name__ == '__main__':
    unittest.main()
