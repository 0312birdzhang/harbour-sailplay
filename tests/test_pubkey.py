"""Known-answer tests for Curve25519 and Ed25519.

Every expected value is quoted from RFC 7748 (X25519, sections 5.2 and 6.1)
or RFC 8032 (Ed25519, section 7.1); no vector is inferred. Cross-checks
against the ``cryptography`` package live in test_pubkey_reference.py.
"""

import pytest

from carplay_proto import crypto
from carplay_proto import pubkey


def unhex(text):
    return bytes.fromhex(text.replace(" ", ""))


# RFC 7748 section 5.2: scalar multiplication on Curve25519, scalars given
# unclamped. In the second vector the published hex u-coordinate has bit 255
# set in error (RFC 7748 Errata-ID 5028, Verified); the base-10 number printed
# alongside it in the RFC is the masked value, so the input is quoted as
# ...a413.
_RFC_CURVE_INPUTS = (
    ("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4",
     "e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c",
     "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"),
    ("4b66e9d4d1b4673c5ad22691957d6af5c11b6421e0ea01d42ca4169e7918ba0d",
     "e5210f12786811d3f4b7959d0538ae2c31dbe7106fc03c3efc4cd549c715a413",
     "95cbde9476e8907d7aade45cb4b873f88b595a68799fa152e6f8f7647aac7957"),
)


@pytest.mark.parametrize("scalar_hex, u_hex, result_hex", _RFC_CURVE_INPUTS)
def test_rfc7748_52_curve_scalar_multiplication(scalar_hex, u_hex, result_hex):
    result = pubkey.scalar_mult(unhex(scalar_hex), unhex(u_hex))
    assert result == unhex(result_hex)


# RFC 7748 section 6.1: the X25519 test vector.
_ALICE_SECRET = unhex(
    "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
_ALICE_PUBLIC = unhex(
    "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a")
_BOB_SECRET = unhex(
    "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
_BOB_PUBLIC = unhex(
    "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f")
_SHARED_SECRET = unhex(
    "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742")


def test_rfc7748_61_x25519_key_exchange():
    assert pubkey.x25519_public(_ALICE_SECRET) == _ALICE_PUBLIC
    assert pubkey.x25519_public(_BOB_SECRET) == _BOB_PUBLIC
    assert pubkey.x25519_shared(_ALICE_SECRET, _BOB_PUBLIC) == _SHARED_SECRET
    assert pubkey.x25519_shared(_BOB_SECRET, _ALICE_PUBLIC) == _SHARED_SECRET


def test_clamp_scalar_matches_rfc7748_53():
    secret = b"\xff" + bytes(30) + b"\xff"
    clamped = pubkey.clamp_scalar(secret)
    assert clamped[:1] == b"\xf8"
    assert clamped[-1:] == b"\x7f"
    assert clamped[1:-1] == secret[1:-1]


def test_clamp_scalar_is_idempotent():
    for _ in range(25):
        secret = pubkey.x25519_generate().secret
        assert pubkey.clamp_scalar(secret) == secret


def test_x25519_shared_clamps_a_raw_scalar():
    alice_raw = bytes(range(1, 33))
    bob_raw = bytes(range(33, 65))
    assert pubkey.x25519_shared(alice_raw, pubkey.x25519_public(bob_raw)) == \
        pubkey.x25519_shared(bob_raw, pubkey.x25519_public(alice_raw))


def test_x25519_generate_returns_a_matching_pair():
    pair = pubkey.x25519_generate()
    assert len(pair.secret) == pubkey.X25519_KEY_BYTES
    assert len(pair.public) == pubkey.X25519_KEY_BYTES
    assert pubkey.x25519_public(pair.secret) == pair.public


def test_x25519_generate_is_random():
    assert pubkey.x25519_generate() != pubkey.x25519_generate()


@pytest.mark.parametrize("length", [0, 1, 31, 33])
def test_x25519_rejects_bad_lengths(length):
    with pytest.raises(crypto.CryptoError):
        pubkey.x25519_public(bytes(length))
    with pytest.raises(crypto.CryptoError):
        pubkey.x25519_shared(bytes(32), bytes(length))


# RFC 8032 section 7.1, tests 1 and 2.
_ED25519_TEST_VECTORS = (
    (unhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"),
     unhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"),
     b"",
     unhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
           "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")),
    (unhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"),
     unhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"),
     b"r",
     unhex("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
           "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")),
)


@pytest.mark.parametrize("seed, public, message, signature", _ED25519_TEST_VECTORS)
def test_rfc8032_71_sign(seed, public, message, signature):
    assert pubkey.ed25519_public(seed) == public
    assert pubkey.ed25519_sign(seed, message) == signature
    assert pubkey.ed25519_verify(public, message, signature) is True


@pytest.mark.parametrize("seed, public, message, signature", _ED25519_TEST_VECTORS)
def test_ed25519_signatures_are_deterministic(seed, public, message, signature):
    assert pubkey.ed25519_sign(seed, message) == signature
    assert pubkey.ed25519_sign(seed, message) == pubkey.ed25519_sign(seed, message)


@pytest.mark.parametrize("size", [0, 1, 2, 33, 1024])
def test_ed25519_round_trip(size):
    seed = bytes((i * 17 + 1) & 0xff for i in range(32))
    public = pubkey.ed25519_public(seed)
    data = bytes((i * 3) & 0xff for i in range(size))
    signature = pubkey.ed25519_sign(seed, data)
    assert len(signature) == pubkey.ED25519_SIGNATURE_BYTES
    assert pubkey.ed25519_verify(public, data, signature) is True


def test_ed25519_rejects_tampered_signatures():
    seed = bytes(range(32))
    public = pubkey.ed25519_public(seed)
    data = b"the pairing message"
    signature = bytearray(pubkey.ed25519_sign(seed, data))

    point_r = bytearray(signature[:32])
    point_r[0] ^= 0x01
    tampered = bytes(point_r) + bytes(signature[32:])
    assert pubkey.ed25519_verify(public, data, tampered) is False

    scalar = bytearray(signature[32:])
    scalar[0] ^= 0x01
    tampered = bytes(signature[:32]) + bytes(scalar)
    assert pubkey.ed25519_verify(public, data, tampered) is False


def test_ed25519_rejects_a_changed_message():
    pair = pubkey.ed25519_from_seed(bytes(range(32)))
    signature = pubkey.ed25519_sign(pair.secret, b"one")
    assert pubkey.ed25519_verify(pair.public, b"one", signature) is True
    assert pubkey.ed25519_verify(pair.public, b"two", signature) is False


def test_ed25519_rejects_the_wrong_public_key():
    signer = pubkey.ed25519_from_seed(bytes(range(32)))
    impostor = pubkey.ed25519_from_seed(bytes(range(33, 65)))
    signature = pubkey.ed25519_sign(signer.secret, b"m")
    assert pubkey.ed25519_verify(impostor.public, b"m", signature) is False


@pytest.mark.parametrize("signature", [
    b"", b"x", b"\x00" * 63, b"\x00" * 65, b"\xff" * 64,
    _ED25519_TEST_VECTORS[0][3][:32] + b"\xff" * 32,
])
def test_ed25519_verify_never_raises(signature):
    public = pubkey.ed25519_public(bytes(range(32)))
    assert pubkey.ed25519_verify(public, b"m", signature) is False


@pytest.mark.parametrize("public", [b"", b"\x00" * 31, b"\x00" * 33])
def test_ed25519_verify_rejects_bad_public_keys(public):
    signature = pubkey.ed25519_sign(bytes(range(32)), b"m")
    assert pubkey.ed25519_verify(public, b"m", signature) is False


def test_ed25519_scalar_follows_rfc8032_pruning():
    seed = b"\x00" * 32
    digest = crypto.sha512(seed)
    first_octet = digest[0] & 0xf8
    last_octet = (digest[31] & 0x7f) | 0x40
    expected_bytes = bytes([first_octet]) + digest[1:31] + bytes([last_octet])
    scalar = pubkey.ed25519_scalar(seed)
    assert scalar == int.from_bytes(expected_bytes, "little")
    assert scalar & 7 == 0
    assert scalar >> 255 == 0
    assert (scalar >> 254) & 1 == 1


def test_ed25519_coordinate_round_trip():
    for offset in range(0, 16):
        seed = bytes(range(offset, offset + 32))
        public = pubkey.ed25519_public(seed)
        point = pubkey.point_decode(public)
        assert point is not None
        assert pubkey.point_encode(point) == public


def test_ed25519_decode_rejects_an_out_of_range_y():
    assert pubkey.point_decode(b"\xff" * 32) is None


def test_ed25519_decode_rejects_a_wrong_length():
    assert pubkey.point_decode(b"\x00" * 31) is None
    assert pubkey.point_decode(b"\x00" * 33) is None


def test_ed25519_neutral_point_encoding():
    assert pubkey.point_encode(pubkey._ED25519_INFINITE) == b"\x01" + b"\x00" * 31


def test_ed25519_base_point_has_the_documented_order():
    assert pubkey.point_equal(
        pubkey.point_mult(pubkey._ED25519_Q, pubkey._ED25519_BASE_POINT),
        pubkey._ED25519_INFINITE) is True


def test_ed25519_generate_returns_a_matching_pair():
    pair = pubkey.ed25519_generate()
    assert len(pair.secret) == pubkey.ED25519_SEED_BYTES
    assert len(pair.public) == pubkey.ED25519_PUBLIC_BYTES
    assert pubkey.ed25519_public(pair.secret) == pair.public


def test_ed25519_generate_is_random():
    assert pubkey.ed25519_generate() != pubkey.ed25519_generate()


def test_ed25519_from_seed_is_deterministic():
    seed = bytes(range(32))
    assert pubkey.ed25519_from_seed(seed) == pubkey.ed25519_from_seed(seed)
    assert pubkey.ed25519_from_seed(seed) != \
        pubkey.ed25519_from_seed(bytes(range(33, 65)))


@pytest.mark.parametrize("length", [0, 1, 31, 33])
def test_ed25519_rejects_bad_seed_lengths(length):
    with pytest.raises(crypto.CryptoError):
        pubkey.ed25519_public(bytes(length))
    with pytest.raises(crypto.CryptoError):
        pubkey.ed25519_sign(bytes(length), b"m")
    with pytest.raises(crypto.CryptoError):
        pubkey.ed25519_from_seed(bytes(length))
