"""RFC 8439 known-answer tests for the ChaCha20-Poly1305 primitives.

Every expected value below is quoted from RFC 8439; no vector is inferred.
"""

import hashlib
import hmac
import struct

import pytest

from carplay_proto import crypto


ZERO_KEY = bytes(range(0x00, 0x20))
KEY_80_9F = bytes(range(0x80, 0xa0))

SUNSCREEN = b"Ladies and Gentlemen of the class of '99: If I could offer you " \
            b"only one tip for the future, sunscreen would be it."

NONCE_232 = b"\x00\x00\x00\x09\x00\x00\x00\x4a\x00\x00\x00\x00"
NONCE_242 = b"\x00" * 7 + b"\x4a\x00\x00\x00\x00"
NONCE_262 = b"\x00" * 5 + bytes(range(0x01, 0x08))
NONCE_282 = b"\x07\x00\x00\x00\x40\x41\x42\x43\x44\x45\x46\x47"


def xor(first, second):
    """Byte-wise XOR.

    Written out by hand because ``bytes ^ bytes`` is not portable: some
    CPython builds strip the number slots off the immutable sequence
    types, and the module under test avoids the operator too.
    """
    return bytes(a ^ b for a, b in zip(first, second))


def test_rfc8439_211_quarter_round():
    state = [0x11111111, 0x01020304, 0x9b8d6f43, 0x01234567]
    crypto._quarter_round(state, 0, 1, 2, 3)
    assert state == [0xea2a92f4, 0xcb1cf8ce, 0x4581472e, 0x5881c4bb]


def test_rfc8439_232_state_layout():
    packed = crypto._SIGMA + ZERO_KEY + b"\x01\x00\x00\x00" + NONCE_232
    words = struct.unpack("<16I", packed)
    assert words[0:4] == (0x61707865, 0x3320646e, 0x79622d32, 0x6b206574)
    assert words[12] == 1
    assert words[13:16] == (0x09000000, 0x4a000000, 0x00000000)


BLOCK_232 = bytes.fromhex(
    "10f1e7e4d13b5915500fdd1fa32071c4"
    "c7d1f4c733c068030422aa9ac3d46c4e"
    "d2826446079faa0914c2d705d98b02a2"
    "b5129cd1de164eb9cbd083e8a2503c4e")


def test_rfc8439_232_block_function():
    assert crypto.chacha20_block(ZERO_KEY, NONCE_232, 1) == BLOCK_232


CIPHERTEXT_242 = bytes.fromhex(
    "6e2e359a2568f98041ba0728dd0d6981"
    "e97e7aec1d4360c20a27afccfd9fae0b"
    "f91b65c5524733ab8f593dabcd62b357"
    "1639d624e65152ab8f530c359f0861d8"
    "07ca0dbf500d6a6156a38e088a22b65e"
    "52bc514d16ccf806818ce91ab7793736"
    "5af90bbf74a35be6b40b8eedf2785e42"
    "874d")


def test_rfc8439_242_chacha20_cipher():
    assert crypto.chacha20_xor(ZERO_KEY, NONCE_242, 1, SUNSCREEN) == CIPHERTEXT_242


def test_chacha20_xor_round_trip():
    assert crypto.chacha20_xor(ZERO_KEY, NONCE_242, 1, CIPHERTEXT_242) == SUNSCREEN


def test_chacha20_single_block_equals_stream_cipher():
    keystream = crypto.chacha20_xor(ZERO_KEY, NONCE_242, 1, b"\x00" * 64)
    assert keystream == xor(CIPHERTEXT_242[:64], SUNSCREEN[:64])


def test_chacha20_uses_a_distinct_block_per_counter():
    block_one = crypto.chacha20_block(ZERO_KEY, NONCE_242, 1)
    block_two = crypto.chacha20_block(ZERO_KEY, NONCE_242, 2)
    assert block_one != block_two
    assert block_one == xor(CIPHERTEXT_242[:64], SUNSCREEN[:64])


def test_chacha20_multi_block_xor_is_blockwise():
    plaintext = bytes((i * 3) & 0xff for i in range(200))
    result = crypto.chacha20_xor(ZERO_KEY, NONCE_242, 1, plaintext)
    blocks = b""
    for index, counter in enumerate((1, 2, 3, 4)):
        chunk = plaintext[index * 64:(index + 1) * 64]
        block = crypto.chacha20_block(ZERO_KEY, NONCE_242, counter)
        blocks += xor(chunk, block[:len(chunk)])
    assert result == blocks


def test_key_nonce_and_counter_ranges_are_enforced():
    with pytest.raises(crypto.CryptoError):
        crypto.chacha20_block(b"", NONCE_242, 1)
    with pytest.raises(crypto.CryptoError):
        crypto.chacha20_block(ZERO_KEY[:-1], NONCE_242, 1)
    with pytest.raises(crypto.CryptoError):
        crypto.chacha20_block(ZERO_KEY + b"\x00", NONCE_242, 1)
    with pytest.raises(crypto.CryptoError):
        crypto.chacha20_block(ZERO_KEY, NONCE_242[:-1], 1)
    with pytest.raises(crypto.CryptoError):
        crypto.chacha20_block(ZERO_KEY, NONCE_242 + b"\x00", 1)
    with pytest.raises(crypto.CryptoError):
        crypto.chacha20_block(ZERO_KEY, NONCE_242, 1 << 32)
    with pytest.raises(crypto.CryptoError):
        crypto.chacha20_block(ZERO_KEY, NONCE_242, -1)
    with pytest.raises(crypto.CryptoError):
        crypto.chacha20_xor(ZERO_KEY, NONCE_242, 1 << 32, b"abc")


POLY_KEY = bytes.fromhex(
    "85d6be7857556d337f4452fe42d506a8"
    "0103808afb0db2fd4abff6af4149f51b")
POLY_MESSAGE = b"Cryptographic Forum Research Group"
POLY_TAG = bytes.fromhex("a8061dc1305136c6c22b8baf0c0127a9")


def test_rfc8439_252_poly1305_tag():
    assert crypto.poly1305_mac(POLY_KEY, POLY_MESSAGE) == POLY_TAG


def test_rfc8439_252_poly1305_clamped_r():
    assert format(crypto._clamp_r(POLY_KEY[:16]), "x") == \
        "806d5400e52447c036d555408bed685"
    assert crypto._clamp_r(POLY_KEY[:16]) != int.from_bytes(
        POLY_KEY[:16], "little")


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 31, 32, 33, 48, 64, 100])
def test_poly1305_tag_is_16_bytes(size):
    assert len(crypto.poly1305_mac(POLY_KEY, b"abc" * size)) == 16


@pytest.mark.parametrize("size", [0, 1, 15, 31, 33])
def test_poly1305_rejects_bad_key_length(size):
    with pytest.raises(crypto.CryptoError):
        crypto.poly1305_mac(bytes(size), b"message")


def test_poly1305_distinguishes_messages():
    assert crypto.poly1305_mac(POLY_KEY, b"abc") != crypto.poly1305_mac(
        POLY_KEY, b"abd")
    assert crypto.poly1305_mac(POLY_KEY, b"abc") != crypto.poly1305_mac(
        POLY_KEY, b"abcd")
    assert crypto.poly1305_mac(POLY_KEY, b"abc") != crypto.poly1305_mac(
        POLY_KEY, b"abc\xff")


def test_poly1305_distinguishes_keys():
    key_b = POLY_KEY[:-1] + bytes([POLY_KEY[-1] ^ 1])
    assert crypto.poly1305_mac(POLY_KEY, POLY_MESSAGE) != crypto.poly1305_mac(
        key_b, POLY_MESSAGE)


POLY_KEY_262 = bytes.fromhex(
    "8ad5a08b905f81cc815040274ab29471a833b637e3fd0da508dbb8e2fdd1a646")


def test_rfc8439_262_poly1305_key_generation():
    assert crypto.poly1305_key(KEY_80_9F, NONCE_262) == POLY_KEY_262
    assert crypto.poly1305_key(KEY_80_9F, NONCE_262, 0) == POLY_KEY_262
    assert crypto.poly1305_key(KEY_80_9F, NONCE_262) == \
        crypto.chacha20_block(KEY_80_9F, NONCE_262, 0)[:32]


def test_poly1305_key_depends_on_counter():
    assert crypto.poly1305_key(KEY_80_9F, NONCE_262, 0) != \
        crypto.poly1305_key(KEY_80_9F, NONCE_262, 1)


AEAD_AAD = b"PQRS" + bytes(range(0xc0, 0xc8))
AEAD_CIPHERTEXT = bytes.fromhex(
    "d31a8d34648e60db7b86afbc53ef7ec2"
    "a4aded51296e08fea9e2b5a736ee62d6"
    "3dbea45e8ca9671282fafb69da92728b"
    "1a71de0a9e060b2905d6a5b67ecd3b36"
    "92ddbd7f2d778b8c9803aee328091b58"
    "fab324e4fad675945585808b4831d7bc"
    "3ff4def08e4b7a9de576d26586cec64b"
    "6116")
AEAD_TAG = bytes.fromhex("1ae10b594f09e26a7e902ecbd0600691")


def test_rfc8439_282_aead_seal():
    out = crypto.chacha_seal(KEY_80_9F, NONCE_282, SUNSCREEN, AEAD_AAD)
    assert out == AEAD_CIPHERTEXT + AEAD_TAG


def test_rfc8439_282_aead_open():
    assert crypto.chacha_open(KEY_80_9F, NONCE_282,
                              AEAD_CIPHERTEXT + AEAD_TAG, AEAD_AAD) == SUNSCREEN


def test_rfc8439_282_aead_mac_input():
    assert crypto._aead_message(AEAD_AAD, AEAD_CIPHERTEXT) == \
        AEAD_AAD + b"\x00" * 4 + AEAD_CIPHERTEXT + b"\x00" * 14 + \
        (12).to_bytes(8, "little") + (114).to_bytes(8, "little")


def test_rfc8439_282_aead_mac_input_empty_fields():
    assert crypto._aead_message(b"", b"") == b"" + (0).to_bytes(
        8, "little") + (0).to_bytes(8, "little")


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 31, 32, 48, 64, 100, 4096])
def test_aead_round_trip(size):
    plaintext = bytes((i * 7 + 1) & 0xff for i in range(size))
    aad = b"aad" * (size // 11)
    sealed = crypto.chacha_seal(KEY_80_9F, NONCE_282, plaintext, aad)
    assert len(sealed) == size + crypto.TAG_BYTES
    assert crypto.chacha_open(KEY_80_9F, NONCE_282, sealed, aad) == plaintext


def test_aead_authentication_failure_modes():
    sealed = crypto.chacha_seal(KEY_80_9F, NONCE_282, SUNSCREEN, AEAD_AAD)

    tampered = bytearray(sealed)
    tampered[3] ^= 0x01
    with pytest.raises(crypto.AuthenticationError):
        crypto.chacha_open(KEY_80_9F, NONCE_282, bytes(tampered), AEAD_AAD)

    tag = bytearray(sealed[-crypto.TAG_BYTES:])
    tag[0] ^= 0x80
    with pytest.raises(crypto.AuthenticationError):
        crypto.chacha_open(KEY_80_9F, NONCE_282,
                           sealed[:-crypto.TAG_BYTES] + bytes(tag), AEAD_AAD)

    with pytest.raises(crypto.AuthenticationError):
        crypto.chacha_open(KEY_80_9F, NONCE_282, sealed, AEAD_AAD[:-1] + b"\x00")

    with pytest.raises(crypto.AuthenticationError):
        crypto.chacha_open(KEY_80_9F[:-1] + b"\x00", NONCE_282, sealed, AEAD_AAD)

    with pytest.raises(crypto.AuthenticationError):
        crypto.chacha_open(KEY_80_9F, NONCE_282[:-1] + b"\x00", sealed, AEAD_AAD)

    with pytest.raises(crypto.AuthenticationError):
        crypto.chacha_open(KEY_80_9F, NONCE_282, sealed[:-crypto.TAG_BYTES], AEAD_AAD)

    with pytest.raises(crypto.AuthenticationError):
        crypto.chacha_open(KEY_80_9F, NONCE_282, sealed[:-crypto.TAG_BYTES - 1], AEAD_AAD)


def test_aead_accepts_empty_plaintext_and_aad():
    sealed = crypto.chacha_seal(KEY_80_9F, NONCE_282, b"", b"")
    assert len(sealed) == crypto.TAG_BYTES
    assert crypto.chacha_open(KEY_80_9F, NONCE_282, sealed, b"") == b""


def test_aead_rejects_too_short_input():
    with pytest.raises(crypto.AuthenticationError):
        crypto.chacha_open(KEY_80_9F, NONCE_282, b"\x00" * 15, b"")


def test_max_encrypt_bytes_is_rfc_aead_p_max():
    assert crypto.MAX_ENCRYPT_BYTES == 274877906880 == \
        (2 ** 32 - 1) * crypto.BLOCK_BYTES


def test_nonce64_layout():
    assert crypto.nonce64(0) == b"\x00" * 12
    assert crypto.nonce64(1) == b"\x00\x00\x00\x00\x01\x00\x00\x00" \
                                b"\x00\x00\x00\x00"
    assert crypto.nonce64(0x0102030405060708) == \
        b"\x00" * 4 + b"\x08\x07\x06\x05\x04\x03\x02\x01"
    assert crypto.nonce64(0xffffffffffffffff) == b"\x00" * 4 + b"\xff" * 8
    assert crypto.nonce64(1) != b"\x01" + b"\x00" * 11


@pytest.mark.parametrize("bad", [-1, 1 << 64, 1 << 128])
def test_nonce64_rejects_bad_counter(bad):
    with pytest.raises(crypto.CryptoError):
        crypto.nonce64(bad)


def test_nonce_label_layout():
    assert crypto.nonce_label("abcd") == b"\x00" * 4 + b"abcd\x00\x00\x00\x00"
    assert crypto.nonce_label("") == b"\x00" * 12
    assert crypto.nonce_label("abcdefgh") == b"\x00" * 4 + b"abcdefgh"
    assert crypto.nonce_label("abcdefghij") == b"\x00" * 4 + b"abcdefgh"
    assert crypto.nonce_label("Pair-Setup-Encrypt-Salt") == \
        b"\x00" * 4 + b"Pair-Set"


def test_nonce64_and_nonce_label_agree_on_empty():
    assert crypto.nonce64(0) == crypto.nonce_label("")


def test_sha512_concatenates_parts():
    assert crypto.sha512(b"abc", b"def") == hashlib.sha512(b"abcdef").digest()
    assert crypto.sha512() == hashlib.sha512().digest()
    assert crypto.sha512(b"\x00" * 100) == hashlib.sha512(b"\x00" * 100).digest()


def _hkdf_reference(ikm, salt, info, length):
    if not salt:
        salt = b"\x00" * crypto.SHA512_DIGEST_BYTES
    if len(salt) > crypto.SHA512_DIGEST_BYTES:
        salt = salt[:crypto.SHA512_DIGEST_BYTES]
    prk = hmac.new(salt, ikm, hashlib.sha512).digest()
    out, transcript, counter = bytearray(), b"", 1
    while len(out) < length:
        transcript = hmac.new(prk, transcript + info + bytes([counter]),
                              hashlib.sha512).digest()
        out.extend(transcript)
        counter += 1
    return bytes(out[:length])


@pytest.mark.parametrize("ikm,salt,info,length", [
    (b"", b"", b"", 32),
    (b"ikm", b"", b"", 64),
    (b"\x00" * 22, b"salt", b"info", 42),
    (b"key", b"a" * 80, b"x" * 200, 129),
    (b"shared secret", b"r\x0b", b"CarPlay", 64),
    (b"ikm", b"salt", b"", 1),
    (b"ikm", b"salt", b"", 64),
    (b"ikm", b"salt", b"", 65),
    (b"ikm", b"salt", b"", 255 * 64),
])
def test_hkdf_sha512_matches_reference_definition(ikm, salt, info, length):
    assert crypto.hkdf_sha512(ikm, salt, info, length) == \
        _hkdf_reference(ikm, salt, info, length)


def test_hkdf_sha512_empty_salt_means_zero_salt():
    assert crypto.hkdf_sha512(b"ikm", None, b"info", 32) == \
        crypto.hkdf_sha512(b"ikm", b"", b"info", 32)


def test_hkdf_sha512_oversized_salt_is_truncated():
    assert crypto.hkdf_sha512(b"ikm", b"a" * 200, b"", 32) == \
        crypto.hkdf_sha512(b"ikm", b"a" * 64, b"", 32)
    assert crypto.hkdf_sha512(b"ikm", b"a" * 65, b"", 32) == \
        crypto.hkdf_sha512(b"ikm", b"a" * 64, b"", 32)


def test_hkdf_sha512_separates_the_info_fields():
    assert crypto.hkdf_sha512(b"ikm", b"salt", b"ab", 64) != \
        crypto.hkdf_sha512(b"ikm", b"salt", b"a", 64)
    assert crypto.hkdf_sha512(b"ikm", b"salt", b"ab", 64) != \
        crypto.hkdf_sha512(b"ikm", b"salt", b"a", 128)


@pytest.mark.parametrize("bad", [0, -1, 255 * 64 + 1, 1 << 40])
def test_hkdf_sha512_rejects_bad_length(bad):
    with pytest.raises(crypto.CryptoError):
        crypto.hkdf_sha512(b"ikm", b"salt", b"", bad)


def test_mac_bits_constant():
    assert crypto.MAC_BITS == 128 == crypto.TAG_BYTES * 8
