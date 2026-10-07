import unittest
from carplay_proto.wire import Frame, ProtocolError, encode_param
from carplay_proto.wireless import parse_wifi_configuration, request_wifi_configuration, parse_start_session


class WirelessTests(unittest.TestCase):
    def test_start_session_ipv6_and_private_credentials(self):
        import struct
        group = (encode_param(0, b'CarAP\0') + encode_param(1, b'secret123\0') +
                 encode_param(3, b'fe80::1\0'))
        session = parse_start_session(Frame(0x4301, encode_param(1, group) + encode_param(2, struct.pack('>I', 7000))))
        self.assertEqual(session.addresses, ['fe80::1'])
        self.assertEqual(session.port, 7000)
        self.assertNotIn('secret123', repr(session))
        with self.assertRaises(ProtocolError):
            parse_start_session(Frame(0x4301, encode_param(1, group) + encode_param(2, b'\0' * 4)))

    def test_phone_request(self):
        self.assertEqual(request_wifi_configuration().encoded(), bytes.fromhex('404000065702'))

    def test_credentials_and_unknown_security(self):
        body = (encode_param(1, b'CarAP\0') + encode_param(2, b'secret123\0') +
                encode_param(3, b'\x04') + encode_param(4, b'\x24'))
        config = parse_wifi_configuration(Frame(0x5703, body))
        self.assertEqual((config.ssid, config.passphrase, config.security, config.channel),
                         ('CarAP', 'secret123', 4, 36))
        self.assertNotIn('secret123', repr(config))
        self.assertNotIn('CarAP', repr(config))

    def test_invalid_fields(self):
        for body in (b'', encode_param(1, b'no-terminator'),
                     encode_param(1, b'car\0') * 2,
                     encode_param(1, b'car\0') + encode_param(3, b'\0\0')):
            with self.assertRaises(ProtocolError):
                parse_wifi_configuration(Frame(0x5703, body))


if __name__ == '__main__':
    unittest.main()
