import unittest
from carplay_proto.airplaypair import pair_setup, pair_verify
from carplay_proto.pairverify import PairVerify
from carplay_proto.pairsetup import PairSetup, ROLE_ACCESSORY, METHOD_PAIR_SETUP
from carplay_proto import tlv8


class Peer:
    def __init__(self):
        self.exchange = PairSetup(ROLE_ACCESSORY, 'car', bytes(range(32)))
        self.calls = 0
    def request(self, method, path, body, headers):
        if path == '/pair-verify':
            if not hasattr(self, 'verify'):
                self.verify = PairVerify(ROLE_ACCESSORY, 'car', bytes(range(32)), self.exchange.peer_long_term_public_key)
            return 200, {}, self.verify.handle(body)
        self.calls += 1
        if self.calls == 1:
            fields = tlv8.decode(body)
            if bytes(fields.get(tlv8.TYPE_METHOD)) != b'\0':
                raise AssertionError('AirPlay method must be numeric zero')
            body = tlv8.encode([tlv8.Item(tlv8.TYPE_STATE,b'\1'), tlv8.Item(tlv8.TYPE_METHOD,METHOD_PAIR_SETUP)])
        return 200, {}, self.exchange.handle(body)

    def enable_encryption(self, keys):
        self.keys = keys


class PairingTests(unittest.TestCase):
    def test_controller_checks_peer_proof(self):
        peer = Peer()
        exchange = pair_setup(peer, 'tablet', bytes(range(32,64)))
        self.assertTrue(exchange.is_paired)
        self.assertEqual(peer.calls, 3)
        self.assertEqual(exchange.peer_id, b'car')
        verified = pair_verify(peer, 'tablet', bytes(range(32,64)), exchange)
        self.assertTrue(verified.is_verified)
        self.assertEqual(peer.keys.read_key, peer.verify.control_keys.write_key)


if __name__ == '__main__':
    unittest.main()
