"""Phone-role AirPlay Pair-Setup over RTSP, with strict peer proof checks."""
from .pairsetup import PairSetup, ROLE_CONTROLLER
from . import tlv8
from .pairverify import PairVerify


def pair_setup(client, pairing_id, private_key):
    exchange = PairSetup(ROLE_CONTROLLER, pairing_id, private_key)
    # AirPlay/HomeKit's method is numeric 0, unlike the older local receiver codec.
    outgoing = tlv8.encode([tlv8.Item(tlv8.TYPE_STATE, b'\x01'), tlv8.Item(tlv8.TYPE_METHOD, b'\x00')])
    for expected_state in (2, 4, 6):
        status, headers, body = client.request('POST', '/pair-setup', outgoing,
            {'Content-Type':'application/pairing+tlv8','X-Apple-HKP':'2','User-Agent':'AirPlay/566.25.21'})
        if status != 200:
            raise ValueError('Pair-Setup HTTP status {}'.format(status))
        items = tlv8.decode(body)
        if items.get(tlv8.TYPE_ERROR) is not None:
            raise ValueError('Pair-Setup remote TLV error {}'.format(bytes(items.get(tlv8.TYPE_ERROR)).hex()))
        if bytes(items.get(tlv8.TYPE_STATE, b'')) != bytes([expected_state]):
            raise ValueError('Pair-Setup unexpected state')
        outgoing = exchange.handle(body)
        if outgoing is not None and tlv8.decode(outgoing).get(tlv8.TYPE_ERROR) is not None:
            raise ValueError('Pair-Setup peer proof verification failed')
        if expected_state == 4:
            outgoing = exchange.m5()
    if not exchange.is_paired:
        raise ValueError('Pair-Setup did not establish peer identity')
    return exchange


def pair_verify(client, pairing_id, private_key, paired):
    exchange = PairVerify(ROLE_CONTROLLER, pairing_id, private_key, paired.peer_long_term_public_key)
    outgoing = exchange.begin()
    for expected_state in (2, 4):
        status, headers, body = client.request('POST', '/pair-verify', outgoing,
            {'Content-Type':'application/pairing+tlv8','X-Apple-HKP':'2','User-Agent':'AirPlay/566.25.21'})
        if status != 200:
            raise ValueError('Pair-Verify HTTP status {}'.format(status))
        items = tlv8.decode(body)
        if items.get(tlv8.TYPE_ERROR) is not None or bytes(items.get(tlv8.TYPE_STATE,b'')) != bytes([expected_state]):
            raise ValueError('Pair-Verify remote error or unexpected state')
        outgoing = exchange.handle(body)
        if outgoing is not None and tlv8.decode(outgoing).get(tlv8.TYPE_ERROR) is not None:
            raise ValueError('Pair-Verify signature verification failed')
    if not exchange.is_verified or exchange.peer_id != paired.peer_id:
        raise ValueError('Pair-Verify peer identity mismatch')
    client.enable_encryption(exchange.control_keys)
    return exchange
