import unittest
from carplay_proto.display import AnnexBFrames


class DisplayFramesTests(unittest.TestCase):
    def test_fragmented_multislice_waits_for_idr(self):
        units=[b'\x41\x80\xaa',b'\x67\x42\x00\x1f',b'\x68\x01',
               b'\x65\x80\xbb',b'\x65\x40\xcc',b'\x41\x80\xdd',
               b'\x41\x80\xee',b'\x09\xf0']
        stream=b''.join((b'\x00\x00\x01' if i%2 else b'\x00\x00\x00\x01')+n
                        for i,n in enumerate(units))
        parser=AnnexBFrames()
        frames=[]
        for byte in stream:
            frames.extend(parser.feed(bytes([byte])))
        self.assertEqual(frames,[[units[3],units[4]],[units[5]]])
        self.assertEqual(parser.config()[:6],b'\x01\x42\x00\x1f\xff\xe1')

    def test_unbounded_capture_input_rejected(self):
        with self.assertRaises(ValueError):
            AnnexBFrames().feed(bytes(8*1024*1024+1))
