import unittest
import struct
from carplay_proto.airplaytiming import timing_response


class TimingTests(unittest.TestCase):
    def test_response_echoes_transmit_time_and_uses_monotonic_fixed_point(self):
        request = b'\x80\xd2\x00\x07' + bytes(20) + struct.pack('>Q',123)
        response = timing_response(request,1000000000,1500000000)
        self.assertEqual(response[:4],b'\x80\xd3\x00\x07')
        self.assertEqual(struct.unpack('>QQQ',response[8:]),(123,1 << 32,(1 << 32)+(1 << 31)))
        self.assertIsNone(timing_response(request[:20],0,0))
        self.assertIsNone(timing_response(response,0,0))
