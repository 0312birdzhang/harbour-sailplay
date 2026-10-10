import struct
import unittest
from carplay_proto.touch import touch_layout,decode_touch
from carplay_proto.audio import AudioEncoder
from carplay_proto import crypto

class MediaTests(unittest.TestCase):
    def test_diplay_two_contacts_selects_active_finger(self):
        contact=bytes.fromhex('050d0922a102093875089501810215002501093375019501810295078103050126a005093075109501810226d20b09318102c0')
        descriptor=bytes.fromhex('050d0904a101')+contact+contact+bytes.fromhex('c0')
        fields=touch_layout(descriptor)
        first=struct.pack('<BBHH',1,1,720,1513)
        inactive=bytes(6)
        self.assertEqual(decode_touch(fields,first+inactive,1440,3026),(True,719,1512))
        self.assertEqual(decode_touch(fields,inactive+first,1440,3026),(True,719,1512))
        self.assertEqual(decode_touch(fields,inactive*2,1440,3026),(False,0,0))

    def test_touch_bitpacked_and_report_id(self):
        # Report 7: tip bit + padding + absolute 16-bit X and Y.
        descriptor=bytes.fromhex('8507050d09421500250175019501810275079501810105010930150026ff7f7510950181020931150026ff7f751095018102')
        fields=touch_layout(descriptor)
        self.assertEqual(decode_touch(fields,b'\x07\x01'+struct.pack('<HH',32767,32767)),(True,1919,719))
        self.assertEqual(decode_touch(fields,b'\x07\x00'+bytes(4)),(False,0,0))
        with self.assertRaises(ValueError):decode_touch(fields,b'\x07\x01')

    def test_audio_independent_aead_and_pcm_endianness(self):
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        shared=bytes(range(32));encoder=AudioEncoder(shared,12345)
        pcm=struct.pack('<hhhh',1000,-1000,32767,-32768)
        packet=encoder.packet(pcm)
        self.assertEqual(struct.unpack('>BBHII',packet[:12]),(128,100,0,0,0))
        key=crypto.hkdf_sha512(shared,b'DataStream-Salt12345',b'DataStream-Output-Encryption-Key',32)
        decoded=ChaCha20Poly1305(key).decrypt(bytes(4)+packet[-8:],packet[12:-8],packet[4:12])
        self.assertEqual(decoded,struct.pack('>hhhh',1000,-1000,32767,-32768))
        second=encoder.packet(pcm)
        self.assertEqual(struct.unpack('>BBHII',second[:12]),(128,100,1,2,0))
        self.assertEqual(int.from_bytes(second[-8:],'little'),1)
        with self.assertRaises(ValueError):encoder.packet(b'\0')

if __name__=='__main__':unittest.main()
