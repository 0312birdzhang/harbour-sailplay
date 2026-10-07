"""ChaCha20-Poly1305 framing for the CarPlay control channel.

The head unit wraps every control message in

    [2-byte little-endian ciphertext length][ciphertext][16-byte Poly1305 tag]

The two length bytes are the AEAD associated data, so rewriting a length is
authenticated. Each direction uses its own 32-byte key and its own 64-bit
little-endian nonce counter (RFC 8439 section 2.6), which is why the counter
lives here rather than on the primitive.

Sizes and offsets follow the head unit implementation in xcertplay's
``airplay/ControlCipher.kt``; byte order and the AAD choice are both visible
on the wire, not inferred.
"""

import struct

from . import crypto


HEADER_BYTES = 2
TAG_BYTES = crypto.TAG_BYTES
MAX_PAYLOAD_BYTES = 0x4000
FRAGMENT_BYTES = HEADER_BYTES + MAX_PAYLOAD_BYTES + TAG_BYTES
MAX_COUNTER = 0xffffffffffffffff


class Decrypted(object):
    """Plaintext recovered from a buffer plus the bytes that did not yet form
    a complete frame.

    ``rest`` is fed back into the next call so frames split across reads still
    line up.
    """

    __slots__ = ("data", "rest")

    def __init__(self, data, rest):
        self.data = bytes(data)
        self.rest = bytes(rest)

    def __eq__(self, other):
        return (isinstance(other, Decrypted)
                and self.data == other.data
                and self.rest == other.rest)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "Decrypted({}, {} rest)".format(len(self.data), len(self.rest))


class ControlCipher(object):
    """One control channel between the head unit and this device.

    ``read_key`` decrypts frames coming from the head unit, ``write_key``
    encrypts frames going to it. Instantiate one per channel: the control,
    event, screen and audio channels each derive their own key pair.
    """

    def __init__(self, read_key, write_key):
        _check_key(read_key, "read")
        _check_key(write_key, "write")
        self._read_key = bytes(read_key)
        self._write_key = bytes(write_key)
        self._read_counter = 0
        self._write_counter = 0

    @property
    def read_counter(self):
        return self._read_counter

    @property
    def write_counter(self):
        return self._write_counter

    def encrypt(self, plaintext):
        """Frame ``plaintext`` as one or more 0x4000-byte fragments.

        Each fragment consumes a write counter, so a 0x8001-byte message uses
        counters 0 and 1. An empty message still produces one fragment, which
        keeps this in step with the head unit.
        """
        plaintext = bytes(plaintext)
        out = bytearray()
        offset = 0
        while True:
            chunk = plaintext[offset:offset + MAX_PAYLOAD_BYTES]
            header = struct.pack("<H", len(chunk))
            out.extend(header)
            out.extend(crypto.chacha_seal(
                self._write_key, crypto.nonce64(self._write_counter),
                chunk, header))
            self._write_counter = _advance(self._write_counter, "write")
            offset += MAX_PAYLOAD_BYTES
            if offset >= len(plaintext):
                break
        return bytes(out)

    def decrypt(self, buffer):
        """Unframe ``buffer`` into plaintext plus a trailing remainder.

        Raises ``crypto.AuthenticationError`` on a frame whose tag does not
        verify; that counter still points at the offending frame, so the
        channel is only salvageable from the beginning. A frame whose bytes
        have not arrived yet is left in ``rest`` and reported, not raised.
        """
        buffer = bytes(buffer)
        out = bytearray()
        offset = 0
        while len(buffer) - offset >= HEADER_BYTES:
            length = struct.unpack(
                "<H", buffer[offset:offset + HEADER_BYTES])[0]
            frame_end = offset + HEADER_BYTES + length + TAG_BYTES
            if len(buffer) < frame_end:
                break
            header = buffer[offset:offset + HEADER_BYTES]
            sealed = buffer[offset + HEADER_BYTES:frame_end]
            out.extend(crypto.chacha_open(
                self._read_key, crypto.nonce64(self._read_counter),
                sealed, header))
            self._read_counter = _advance(self._read_counter, "read")
            offset = frame_end
        return Decrypted(bytes(out), buffer[offset:])


def _check_key(key, label):
    if len(key) != crypto.KEY_BYTES:
        raise crypto.CryptoError(
            "{} key must be {} bytes, got {}".format(
                label, crypto.KEY_BYTES, len(key)))


def _advance(counter, label):
    if counter >= MAX_COUNTER:
        raise crypto.CryptoError("{} nonce counter exhausted".format(label))
    return counter + 1
