"""ChaCha20-Poly1305 AEAD (RFC 8439) plus HKDF-SHA512 and the CarPlay
nonce builders.

Pure stdlib: CarPlay's control channel and both media streams are built on
these primitives. Apple's libap-lib.so ships its own copies of the same
algorithms (``chacha20_poly1305_encrypt_all_96x32``, ``poly1305``,
``AirPlay_DeriveAESKeySHA512``), but reimplementing them here keeps the
stack dependency-free.
"""

import hashlib
import hmac
import struct


KEY_BYTES = 32
NONCE_BYTES = 12
COUNTER_BYTES = 4
BLOCK_BYTES = 64
TAG_BYTES = 16
POLY1305_BLOCK_BYTES = 16
MAC_BITS = 128
NONCE_LABEL_BYTES = 8
SHA512_DIGEST_BYTES = 64
ROUNDS = 10
MAX_ENCRYPT_BYTES = 0xffffffff * BLOCK_BYTES

_POLY1305_PRIME = (1 << 130) - 5
_POLY1305_TAG_MASK = (1 << 128) - 1
_SIGMA = b"expand 32-byte k"

_COLUMNS = ((0, 4, 8, 12), (1, 5, 9, 13), (2, 6, 10, 14), (3, 7, 11, 15))
_DIAGONALS = ((0, 5, 10, 15), (1, 6, 11, 12), (2, 7, 8, 13), (3, 4, 9, 14))


class CryptoError(ValueError):
    pass


class AuthenticationError(CryptoError):
    pass


def _rotl(value, bits):
    return ((value << bits) | (value >> (32 - bits))) & 0xffffffff


def _quarter_round(state, a, b, c, d):
    state[a] = (state[a] + state[b]) & 0xffffffff
    state[d] = _rotl(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & 0xffffffff
    state[b] = _rotl(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b]) & 0xffffffff
    state[d] = _rotl(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & 0xffffffff
    state[b] = _rotl(state[b] ^ state[c], 7)


def chacha20_block(key, nonce, counter):
    """One 64-byte ChaCha20 keystream block (RFC 8439 section 2.3.1)."""
    _check_key(key)
    _check_nonce(nonce)
    if not 0 <= counter <= 0xffffffff:
        raise CryptoError("counter must fit in u32")

    packed = _SIGMA + key + struct.pack("<I", counter) + nonce
    state = list(struct.unpack("<16I", packed))
    initial = list(state)

    for _ in range(ROUNDS):
        for indices in _COLUMNS:
            _quarter_round(state, *indices)
        for indices in _DIAGONALS:
            _quarter_round(state, *indices)

    out = [(state[i] + initial[i]) & 0xffffffff for i in range(16)]
    return struct.pack("<16I", *out)


def chacha20_xor(key, nonce, counter, data):
    """ChaCha20 stream cipher over ``data`` (RFC 8439 section 2.4)."""
    _check_key(key)
    _check_nonce(nonce)
    if not 0 <= counter <= 0xffffffff:
        raise CryptoError("counter must fit in u32")

    out = bytearray()
    while len(data):
        block = chacha20_block(key, nonce, counter)
        chunk = data[:BLOCK_BYTES]
        out.extend(bytes(a ^ b for a, b in zip(chunk, block)))
        data = data[BLOCK_BYTES:]
        counter = (counter + 1) & 0xffffffff
    return bytes(out)


def poly1305_key(key, nonce, counter=0):
    """Derive the 32-byte Poly1305 key (RFC 8439 section 2.6)."""
    return chacha20_block(key, nonce, counter)[:32]


def poly1305_mac(key, message):
    """16-byte Poly1305 authenticator (RFC 8439 section 2.5)."""
    if len(key) != KEY_BYTES:
        raise CryptoError("poly1305 key must be 32 bytes")

    r = _clamp_r(key[:16])
    s = int.from_bytes(key[16:], "little")

    accumulator = 0
    for index in range(0, len(message), POLY1305_BLOCK_BYTES):
        block = message[index:index + POLY1305_BLOCK_BYTES]
        number = int.from_bytes(block, "little") + (1 << (8 * len(block)))
        accumulator = (r * (accumulator + number)) % _POLY1305_PRIME

    return ((accumulator + s) & _POLY1305_TAG_MASK).to_bytes(
        TAG_BYTES, "little")


def chacha_seal(key, nonce, plaintext, aad=b""):
    """Encrypt and authenticate to ``ciphertext || 16-byte tag`` (RFC 8439
    section 2.8.1)."""
    _check_key(key)
    _check_nonce(nonce)
    if len(plaintext) > MAX_ENCRYPT_BYTES:
        raise CryptoError("plaintext exceeds the AEAD limit")

    ciphertext = chacha20_xor(key, nonce, 1, plaintext)
    tag = poly1305_mac(poly1305_key(key, nonce),
                       _aead_message(aad, ciphertext))
    return ciphertext + tag


def chacha_open(key, nonce, ciphertext_and_tag, aad=b""):
    """Verify and decrypt; raises ``AuthenticationError`` on tampering
    (RFC 8439 section 2.8.1)."""
    _check_key(key)
    _check_nonce(nonce)
    if len(ciphertext_and_tag) < TAG_BYTES:
        raise AuthenticationError("ciphertext too short for a Poly1305 tag")

    ciphertext = ciphertext_and_tag[:-TAG_BYTES]
    tag = ciphertext_and_tag[-TAG_BYTES:]
    expected = poly1305_mac(poly1305_key(key, nonce),
                            _aead_message(aad, ciphertext))

    verified = 0
    for left, right in zip(tag, expected):
        verified |= left ^ right
    if verified:
        raise AuthenticationError("poly1305 tag mismatch")
    return chacha20_xor(key, nonce, 1, ciphertext)


def nonce64(counter):
    """12-byte nonce: four zero bytes followed by a little-endian counter.

    CarPlay sends 64-bit nonces, so the upper 32 bits are the constant
    sender id, zero here (RFC 8439 section 2.6).
    """
    _check_counter(counter)
    return b"\x00" * 4 + struct.pack("<Q", counter)


def nonce_label(label):
    """12-byte nonce: four zero bytes followed by an 8-byte ASCII label."""
    ascii_ = label.encode("ascii", "ignore")[:NONCE_LABEL_BYTES]
    return b"\x00" * 4 + ascii_ + b"\x00" * (NONCE_LABEL_BYTES - len(ascii_))


def sha512(*parts):
    digest = hashlib.sha512()
    for part in parts:
        digest.update(part)
    return digest.digest()


def hkdf_sha512(input_key_material, salt=None, info=b"", length=32):
    """HKDF over SHA-512 (RFC 5869)."""
    if not 0 < length <= 255 * SHA512_DIGEST_BYTES:
        raise CryptoError("hkdf length {} out of range".format(length))
    if salt is None:
        salt = b""
    if not salt:
        salt = b"\x00" * SHA512_DIGEST_BYTES
    if len(salt) > SHA512_DIGEST_BYTES:
        salt = salt[:SHA512_DIGEST_BYTES]

    prk = hmac.new(salt, input_key_material, hashlib.sha512).digest()

    out = bytearray()
    transcript = b""
    counter = 1
    while len(out) < length:
        transcript = hmac.new(prk, transcript + info + struct.pack("B", counter),
                              hashlib.sha512).digest()
        out.extend(transcript)
        counter += 1
    return bytes(out[:length])


def _clamp_r(raw):
    """Clamp the 16 key bytes into the Poly1305 multiplier (RFC 8439 2.5)."""
    clamped = bytearray(raw)
    for index in (3, 7, 11, 15):
        clamped[index] &= 0x0f
    for index in (4, 8, 12):
        clamped[index] &= 0xfc
    return int.from_bytes(clamped, "little")


def _aead_message(aad, ciphertext):
    """The Poly1305 input: AAD, ciphertext and both lengths (RFC 8439
    section 2.8)."""
    return (aad + _pad16(aad) + ciphertext + _pad16(ciphertext) +
            struct.pack("<Q", len(aad)) +
            struct.pack("<Q", len(ciphertext)))


def _pad16(data):
    if len(data) % POLY1305_BLOCK_BYTES:
        pad = POLY1305_BLOCK_BYTES - len(data) % POLY1305_BLOCK_BYTES
        return b"\x00" * pad
    return b""


def _check_key(key):
    if len(key) != KEY_BYTES:
        raise CryptoError("chacha20 key must be 32 bytes, got {}".format(
            len(key)))


def _check_nonce(nonce):
    if len(nonce) != NONCE_BYTES:
        raise CryptoError("chacha20 nonce must be 12 bytes, got {}".format(
            len(nonce)))


def _check_counter(counter):
    if not 0 <= counter <= 0xffffffffffffffff:
        raise CryptoError("nonce counter must fit in u64")
