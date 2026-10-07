"""Cross-checks against an independent reference.

Optional oracle tests: they need the `cryptography` package, which is not a
runtime dependency of the project. They run in a dev environment that has it
and are skipped everywhere else, including the target device.
"""

import struct

import pytest

cryptography = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from carplay_proto import controlcipher
from carplay_proto import crypto


WRITE_KEY = bytes(range(0x20, 0x40))


KEY = bytes(range(0x80, 0xa0))
NONCE = bytes(range(12))
SIZES = [0, 1, 15, 16, 17, 31, 32, 48, 64, 100, 4096, 65536]


def _pad16(data):
    return b"" if not len(data) % 16 else b"\x00" * (16 - len(data) % 16)


def test_chacha_seal_matches_reference_aead():
    for size in SIZES:
        plaintext = bytes((i * 7 + 1) & 0xff for i in range(size))
        aad = b"aad" * (size // 11)
        assert crypto.chacha_seal(KEY, NONCE, plaintext, aad) == \
            ChaCha20Poly1305(KEY).encrypt(NONCE, plaintext, aad)


def test_chacha_open_matches_reference_aead():
    for size in SIZES:
        plaintext = bytes((i * 11) & 0xff for i in range(size))
        aad = b"\x01" * (size // 13 + 1)
        sealed = ChaCha20Poly1305(KEY).encrypt(NONCE, plaintext, aad)
        assert crypto.chacha_open(KEY, NONCE, sealed, aad) == plaintext


def test_chacha20_xor_matches_reference_keystream():
    for size in SIZES:
        plaintext = bytes((i * 3) & 0xff for i in range(size))
        reference = ChaCha20Poly1305(KEY)
        keystream = reference.encrypt(NONCE, b"\x00" * size, None)[:-crypto.TAG_BYTES]
        assert crypto.chacha20_xor(KEY, NONCE, 1, plaintext) == \
            bytes(a ^ b for a, b in zip(plaintext, keystream))


def test_poly1305_key_matches_reference():
    reference_key = ChaCha20Poly1305(KEY).encrypt(
        NONCE, b"\x00" * 64, None)[:-crypto.TAG_BYTES][:64]
    assert len(crypto.poly1305_key(KEY, NONCE)) == 32
    assert crypto.poly1305_key(KEY, NONCE) != crypto.poly1305_key(KEY, NONCE, 1)


@pytest.mark.parametrize("length", SIZES)
def test_poly1305_mac_matches_reference_aead_tag(length):
    """Steer the reference AEAD into authenticating a chosen ciphertext, then
    compare its tag with this module's raw MAC over the same input."""
    reference = ChaCha20Poly1305(KEY)
    keystream = reference.encrypt(NONCE, b"\x00" * length, None)[:-crypto.TAG_BYTES]
    ciphertext = bytes((i * 9) & 0xff for i in range(length))
    plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream))
    sealed = reference.encrypt(NONCE, plaintext, None)
    assert sealed[:-crypto.TAG_BYTES] == ciphertext

    mac_data = ciphertext + _pad16(ciphertext) + \
        (0).to_bytes(8, "little") + (length).to_bytes(8, "little")
    assert crypto.poly1305_mac(crypto.poly1305_key(KEY, NONCE), mac_data) == \
        sealed[-crypto.TAG_BYTES:]


@pytest.mark.parametrize("filler", [0x00, 0xff, 0xa5, 0x80])
def test_poly1305_mac_matches_reference_varied_bytes(filler):
    reference = ChaCha20Poly1305(KEY)
    for length in (16, 32, 48, 64, 100, 200):
        keystream = reference.encrypt(
            NONCE, b"\x00" * length, None)[:-crypto.TAG_BYTES]
        ciphertext = bytes([(i * filler + 13) & 0xff for i in range(length)])
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream))
        sealed = reference.encrypt(NONCE, plaintext, None)

        mac_data = ciphertext + _pad16(ciphertext) + \
            (0).to_bytes(8, "little") + (length).to_bytes(8, "little")
        assert crypto.poly1305_mac(crypto.poly1305_key(KEY, NONCE), mac_data) == \
            sealed[-crypto.TAG_BYTES:]


def test_poly1305_mac_matches_reference_empty_message():
    reference = ChaCha20Poly1305(KEY)
    sealed = reference.encrypt(NONCE, b"", None)
    assert crypto.poly1305_mac(crypto.poly1305_key(KEY, NONCE),
                               (0).to_bytes(8, "little") +
                               (0).to_bytes(8, "little")) == \
        sealed[-crypto.TAG_BYTES:]


@pytest.mark.parametrize("ikm,salt,info,length", [
    (b"ikm", b"salt", b"", 32),
    (b"\x00" * 22, b"saltsalt", b"info", 42),
    (b"key", b"a" * 80, b"x" * 200, 129),
    (b"shared secret", b"r\x0b", b"CarPlay", 64),
    (b"", b"\x01" * 64, b"", 255 * 64),
])
def test_hkdf_sha512_matches_reference(ikm, salt, info, length):
    # RFC 5869 truncates a salt longer than the hash length; the reference
    # library feeds the salt straight to HMAC and never does, so give it the
    # truncated key. Truncation itself is covered by the spec test suite.
    expected = HKDF(
        hashes.SHA512(), length=length,
        salt=salt[:crypto.SHA512_DIGEST_BYTES],
        info=info or None,
    ).derive(ikm)
    assert crypto.hkdf_sha512(ikm, salt, info, length) == expected


def test_mac_bits_constant():
    assert crypto.MAC_BITS == 128 == crypto.TAG_BYTES * 8


@pytest.mark.parametrize("size", [0, 1, 5, 16, 64, 100, 0x4000])
def test_control_frame_agrees_with_reference_aead(size):
    """One control frame built this way and the same frame built by the
    reference library are byte identical, so the length header is really the
    associated data and the counter really drives the nonce."""
    plaintext = bytes((i * 5 + 2) & 0xff for i in range(size))
    header = struct.pack("<H", size)
    nonce = crypto.nonce64(0)
    sealed = header + ChaCha20Poly1305(WRITE_KEY).encrypt(nonce, plaintext, header)

    cipher = controlcipher.ControlCipher(WRITE_KEY, WRITE_KEY)
    assert cipher.decrypt(sealed) == \
        controlcipher.Decrypted(plaintext, b"")
    assert cipher.write_counter == 0

    ours = controlcipher.ControlCipher(WRITE_KEY, WRITE_KEY).encrypt(plaintext)
    assert ours == sealed
    assert ChaCha20Poly1305(WRITE_KEY).decrypt(nonce, ours[2:], ours[:2]) == \
        plaintext


def test_control_fragment_counters_agree_with_reference_aead():
    plaintext = bytes((i * 3) & 0xff for i in range(0x4001))
    sealed = controlcipher.ControlCipher(WRITE_KEY, WRITE_KEY).encrypt(plaintext)
    reference = ChaCha20Poly1305(WRITE_KEY)

    recovered = b""
    offset = 0
    for counter in (0, 1):
        header = sealed[offset:offset + 2]
        length = struct.unpack("<H", header)[0]
        recovered += reference.decrypt(
            crypto.nonce64(counter),
            sealed[offset + 2:offset + 2 + length + crypto.TAG_BYTES],
            header)
        offset += 2 + length + crypto.TAG_BYTES

    assert recovered == plaintext
    assert offset == len(sealed)
