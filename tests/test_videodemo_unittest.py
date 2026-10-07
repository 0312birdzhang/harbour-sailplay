import struct
import unittest
from carplay_proto.videodemo import ScreenEncoder, demo_frames
from carplay_proto import crypto


class VideoDemoTests(unittest.TestCase):
    def test_multislice_and_mixed_start_codes(self):
        data = b'\x00\x00\x00\x01\x67\x42\x00\x1f\x00\x00\x01\x68\x01'
        data += b'\x00\x00\x01\x65\x80\xaa\x00\x00\x00\x01\x65\x40\xbb'
        data += b'\x00\x00\x01\x41\x80\xcc'
        config,frames = demo_frames(data)
        self.assertEqual(config[:6],b'\x01\x42\x00\x1f\xff\xe1')
        self.assertEqual([len(f) for f in frames],[2,1])

    def test_frame_independent_aead_and_counter(self):
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        shared = bytes(range(32))
        key = HKDF(algorithm=hashes.SHA512(),length=32,salt=b'DataStream-Salt42',
                   info=b'DataStream-Output-Encryption-Key').derive(shared)
        encoder = ScreenEncoder(shared,42)
        nal = b'\x65\x80'+bytes(range(256))*100
        for counter in range(2):
            packet = encoder.frame([nal],1500000000)
            self.assertEqual(len(packet),struct.unpack_from('<I',packet)[0]+128)
            plain = ChaCha20Poly1305(key).decrypt(crypto.nonce64(counter),packet[128:],packet[:128])
            self.assertEqual(plain,struct.pack('>I',len(nal))+nal)
            self.assertEqual(struct.unpack_from('<Q',packet,8)[0],(1<<32)+(1<<31))

    def test_configuration_is_plaintext_and_dimensions_are_float(self):
        packet = ScreenEncoder(bytes(32),1).config(b'abcd',1920,720)
        self.assertEqual(packet[4],1)
        self.assertEqual(packet[6],4)
        self.assertEqual(struct.unpack_from('<ff',packet,16),(1920,720))
        self.assertEqual(packet[128:],b'abcd')
