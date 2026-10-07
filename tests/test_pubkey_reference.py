"""Cross-checks of X25519 and Ed25519 against an independent reference.

Optional oracle tests: they need the `cryptography` package, which is not a
runtime dependency of the project. They run in a dev environment that has it
and are skipped everywhere else, including the target device.
"""

import pytest

cryptography = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.asymmetric import x25519

from carplay_proto import pubkey

ENCODED = serialization.Encoding.Raw
RAW = serialization.PublicFormat.Raw

X25519_SECRETS = (
    bytes(32),
    b"\xff" * 32,
    bytes(range(32)),
    bytes((i * 37 + 11) & 0xff for i in range(32)),
    b"\x01" + bytes(31),
)

SEEDS = (
    bytes(32),
    b"\xff" * 32,
    bytes(range(32)),
    bytes((i * 17 + 3) & 0xff for i in range(32)),
)

MESSAGES = (b"", b"hello CarPlay", bytes(range(256)), b"\x00" * 4096)


def _reference_public_key(private_key):
    return private_key.public_key().public_bytes(ENCODED, RAW)


@pytest.mark.parametrize("secret", X25519_SECRETS)
def test_x25519_public_matches_reference(secret):
    reference = x25519.X25519PrivateKey.from_private_bytes(secret)
    assert pubkey.x25519_public(secret) == _reference_public_key(reference)


@pytest.mark.parametrize("secret", X25519_SECRETS)
def test_x25519_shared_matches_reference(secret):
    reference = x25519.X25519PrivateKey.from_private_bytes(secret)
    peer = reference.public_key()
    assert pubkey.x25519_shared(
        secret, peer.public_bytes(ENCODED, RAW)) == reference.exchange(peer)


def _reference_peer(public_bytes):
    return x25519.X25519PublicKey.from_public_bytes(public_bytes)


@pytest.mark.parametrize("left", X25519_SECRETS)
@pytest.mark.parametrize("right", X25519_SECRETS)
def test_x25519_exchange_is_symmetric_with_reference(left, right):
    left_peer = pubkey.x25519_public(left)
    right_peer = pubkey.x25519_public(right)
    reference = x25519.X25519PrivateKey.from_private_bytes(left)
    expected = reference.exchange(_reference_peer(right_peer))

    assert pubkey.x25519_shared(left, right_peer) == expected
    assert pubkey.x25519_shared(right, left_peer) == expected


@pytest.mark.parametrize("seed", SEEDS)
def test_ed25519_public_matches_reference(seed):
    reference = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    assert pubkey.ed25519_public(seed) == _reference_public_key(reference)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("message", MESSAGES)
def test_ed25519_sign_matches_reference(seed, message):
    reference = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    assert pubkey.ed25519_sign(seed, message) == reference.sign(message)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("message", MESSAGES)
def test_signatures_verify_in_reference(seed, message):
    reference = ed25519.Ed25519PublicKey.from_public_bytes(
        pubkey.ed25519_public(seed))
    reference.verify(pubkey.ed25519_sign(seed, message), message)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("message", MESSAGES)
def test_reference_signatures_verify_here(seed, message):
    reference = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    signature = reference.sign(message)
    assert pubkey.ed25519_verify(
        _reference_public_key(reference), message, signature) is True


@pytest.mark.parametrize("seed", SEEDS)
def test_reference_rejects_our_bad_signatures(seed):
    reference = ed25519.Ed25519PublicKey.from_public_bytes(
        pubkey.ed25519_public(seed))
    signature = bytearray(pubkey.ed25519_sign(seed, b"payload"))
    signature[0] ^= 0x01
    assert pubkey.ed25519_verify(
        reference.public_bytes(ENCODED, RAW), b"payload", bytes(signature)) is False


def test_generated_pairs_cross_check_with_reference():
    for _ in range(10):
        x25519_pair = pubkey.x25519_generate()
        reference = x25519.X25519PrivateKey.from_private_bytes(x25519_pair.secret)
        assert x25519_pair.public == _reference_public_key(reference)

        ed25519_pair = pubkey.ed25519_generate()
        reference_key = ed25519.Ed25519PrivateKey.from_private_bytes(
            ed25519_pair.secret)
        assert ed25519_pair.public == _reference_public_key(reference_key)
        reference_key.public_key().verify(
            pubkey.ed25519_sign(ed25519_pair.secret, b"cross check"),
            b"cross check")
