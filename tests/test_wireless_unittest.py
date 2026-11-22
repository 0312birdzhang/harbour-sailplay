import unittest
from carplay_proto.wire import Frame, ProtocolError, encode_param
from carplay_proto.wireless import (parse_wifi_configuration, offers_wireless_carplay, WifiRequestWatch,
                                    peer_supports_wifi_configuration_request,
                                    request_wifi_configuration,
                                    parse_start_session)


class WirelessTests(unittest.TestCase):
    def test_only_accessories_declaring_carplay_messages_are_head_units(self):
        # Fiat/Marelli CARLINE_13, normally and in its plain-Bluetooth mode.
        sent = {0xaa06, 0x5000, 0x5002, 0x5700, 0x5703, 0x5200, 0x5203, 0x00b1, 0x00b3}
        received = {0x4e09, 0x4e0a, 0x4e0c, 0x4e0e, 0x4e0d, 0xea00, 0xea01, 0x5001, 0x5701, 0x5702,
                    0x5201, 0x5202, 0x00b0, 0x00b2, 0x00b4}
        self.assertTrue(offers_wireless_carplay(sent, received))
        self.assertTrue(offers_wireless_carplay(sent - {0x5200, 0x5203}, received - {0x5201, 0x5202}))
        # Notification-driven head units without the explicit Wi-Fi request.
        self.assertTrue(offers_wireless_carplay({0x4301}, set()))
        self.assertTrue(offers_wireless_carplay(set(), {0x4e0d}))
        # Earbuds expose the accessory UUID but only External Accessory messages.
        self.assertFalse(offers_wireless_carplay({0xea03}, {0xea00, 0xea01}))
        self.assertFalse(offers_wireless_carplay([0xea03], []))
        # Peers that omit both lists keep the legacy behavior.
        self.assertTrue(offers_wireless_carplay(set(), set()))

    def test_unanswered_wifi_request_is_reported_once_after_the_patience_delay(self):
        now = [100]
        watch = WifiRequestWatch(clock=lambda: now[0])
        self.assertFalse(watch.overdue())
        watch.requested()
        now[0] = 109
        watch.requested()
        self.assertFalse(watch.overdue())
        now[0] = 110
        self.assertTrue(watch.overdue())
        now[0] = 200
        self.assertFalse(watch.overdue())

    def test_answered_wifi_request_is_never_reported_and_rearms(self):
        now = [100]
        watch = WifiRequestWatch(clock=lambda: now[0])
        watch.requested()
        now[0] = 102
        watch.answered()
        now[0] = 150
        self.assertFalse(watch.overdue())
        watch.requested()
        now[0] = 160
        self.assertTrue(watch.overdue())

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

    def test_phone_request_respects_peer_capabilities(self):
        self.assertTrue(peer_supports_wifi_configuration_request(set()))
        self.assertTrue(peer_supports_wifi_configuration_request({0x4e0d, 0x5702}))
        self.assertFalse(peer_supports_wifi_configuration_request({0x4e09, 0x4e0c, 0x4e0d,
                                                                   0x4e0e, 0x4e04,
                                                                   0xea00, 0xea01}))

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
