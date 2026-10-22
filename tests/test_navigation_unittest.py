import struct
import unittest

from carplay_proto.navigation import (MANEUVER, ROUTE, START, STOP,
                                     NavigationSubscription, maneuver_information,
                                     route_update)
from carplay_proto.wire import Frame, Framer, ProtocolError, encode_param


class NavigationTests(unittest.TestCase):
    def test_route_fields_match_receiver_offsets(self):
        frame = route_update(1, 2, "南京路", "终点", 3661, "12.3", 4, "200", 1)
        self.assertEqual(frame.message_id, ROUTE)
        fields = {p.id: p.payload for p in frame.parameters()}
        self.assertEqual(set(fields), {1, 2, 3, 4, 6, 8, 9, 11, 12})
        self.assertEqual(fields[3], "南京路\0".encode())
        self.assertEqual(fields[6], b"\0\0\0\0\0\0\x0eM")
        self.assertEqual(struct.unpack(">Q", fields[6])[0], 3661)
        self.assertEqual(fields[11], b"200\0")
        self.assertEqual(Framer().offer(frame.encoded()), [frame])

    def test_maneuver_type_is_parameter_three(self):
        frame = maneuver_information(7, "右转道路", 0)
        self.assertEqual(frame.message_id, MANEUVER)
        fields = {p.id: p.payload for p in frame.parameters()}
        self.assertEqual(fields, {3: b"\x07", 4: "右转道路\0".encode(), 7: b"\0"})

    def test_unicode_limit_does_not_split_surrogate_pairs(self):
        frame = maneuver_information(1, "路" * 29 + "🚗", 0)
        text = frame.parameters()[1].payload
        self.assertEqual(text.decode("utf-8"), "路" * 29 + "\0")
        self.assertLessEqual(len(text[:-1].decode().encode("utf-16-le")), 60)

    def test_bad_values_are_not_silently_wrapped(self):
        for value in (-1, 256, True, 1.5, "1"):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                maneuver_information(value, "Road", 0)
        with self.assertRaises(ProtocolError):
            maneuver_information(1, "Road\0suffix", 0)
        with self.assertRaises(ProtocolError):
            route_update(1, 1, "", "", -1, "0", 0, "0", 0)

    def test_subscription_start_and_stop(self):
        subscription = NavigationSubscription()
        start = encode_param(0, b"\0\x09") + b"".join(encode_param(i, b"") for i in (1, 2, 3))
        self.assertTrue(subscription.offer(Frame(START, start)))
        self.assertEqual(subscription.component, 9)
        self.assertEqual(subscription.options, {1, 2, 3})
        # Another display must not stop this subscription.
        subscription.offer(Frame(STOP, encode_param(0, b"\0\x0a")))
        self.assertEqual(subscription.component, 9)
        subscription.offer(Frame(STOP, encode_param(0, b"\0\x09")))
        self.assertIsNone(subscription.component)
        self.assertFalse(subscription.options)

    def test_vendor_stop_byte_order(self):
        subscription = NavigationSubscription()
        subscription.offer(Frame(START, encode_param(0, b"\0\x09")))
        subscription.offer(Frame(STOP, encode_param(0, b"\x09\0")))
        self.assertIsNone(subscription.component)

    def test_malformed_subscription_preserves_last_valid_state(self):
        subscription = NavigationSubscription()
        component = encode_param(0, b"\0\x09")
        subscription.offer(Frame(START, component))
        for payload in (b"", encode_param(0, b"\x09"), component * 2,
                        component + encode_param(1, b"\x01"), b"\0\x03\0\0"):
            with self.subTest(payload=payload), self.assertRaises(ProtocolError):
                subscription.offer(Frame(START, payload))
            self.assertEqual(subscription.component, 9)
        self.assertFalse(subscription.offer(Frame(0x5703, b"")))


if __name__ == "__main__":
    unittest.main()
