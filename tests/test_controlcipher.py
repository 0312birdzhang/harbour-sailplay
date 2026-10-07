"""Tests for the CarPlay control channel framing.

The layout and constants come from the head unit implementation in xcertplay's
airplay/ControlCipher.kt, so these pin the bytes that actually leave the wire
and fail loudly if a later edit changes them.

One caveat the tests lean on: ``read_key`` and ``write_key`` describe the two
directions of a channel held by opposing ends, so a cipher only round trips
when both slots hold the same key. Pairing is covered in
``test_frames_only_decrypt_on_the_peers_side``.
"""

import struct

import pytest

from carplay_proto import controlcipher
from carplay_proto import crypto


KEY = bytes(range(0x20, 0x40))
PEER_KEY = bytes(range(0x40, 0x60))
WRONG_KEY = bytes(range(0x60, 0x80))


def frame_parts(sealed):
    """Split a sealed fragment back into header, ciphertext and tag."""
    header = sealed[:controlcipher.HEADER_BYTES]
    length = struct.unpack("<H", header)[0]
    end = length + controlcipher.HEADER_BYTES
    return header, sealed[controlcipher.HEADER_BYTES:end], sealed[end:]


def test_wire_constants():
    assert controlcipher.HEADER_BYTES == 2
    assert controlcipher.TAG_BYTES == crypto.TAG_BYTES == 16
    assert controlcipher.MAX_PAYLOAD_BYTES == 0x4000
    assert controlcipher.FRAGMENT_BYTES == 0x4012
    assert controlcipher.MAX_COUNTER == 0xffffffffffffffff


def test_nonce_counter_starts_at_zero():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    assert cipher.read_counter == 0
    assert cipher.write_counter == 0


def test_nonce_is_four_zero_bytes_plus_little_endian_counter():
    assert crypto.nonce64(0) == b"\x00" * 12
    assert crypto.nonce64(1) == b"\x00" * 4 + b"\x01\x00\x00\x00\x00\x00\x00\x00"
    assert crypto.nonce64(0x0102030405060708) == \
        b"\x00\x00\x00\x00\x08\x07\x06\x05\x04\x03\x02\x01"


@pytest.mark.parametrize("size", [0, 1, 2, 5, 16, 63, 64, 200, 4096])
def test_round_trip(size):
    plaintext = bytes((i * 7 + 1) & 0xff for i in range(size))
    cipher = controlcipher.ControlCipher(KEY, KEY)
    assert cipher.decrypt(cipher.encrypt(plaintext)) == \
        controlcipher.Decrypted(plaintext, b"")


def test_frame_layout_is_length_ciphertext_tag():
    sealed = controlcipher.ControlCipher(KEY, KEY).encrypt(b"hello")
    header, ciphertext, tag = frame_parts(sealed)
    assert header == b"\x05\x00"
    assert len(sealed) == 2 + 5 + 16
    assert len(ciphertext) == 5
    assert len(tag) == 16


def test_aad_is_the_length_header():
    plaintext = b"hello carplay"
    sealed = controlcipher.ControlCipher(KEY, KEY).encrypt(plaintext)

    assert sealed[2:] == crypto.chacha_seal(
        KEY, crypto.nonce64(0), plaintext, sealed[:2])


def test_empty_plaintext_is_one_frame():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = cipher.encrypt(b"")
    assert sealed == b"\x00\x00" + crypto.chacha_seal(
        KEY, crypto.nonce64(0), b"", b"\x00\x00")
    assert cipher.decrypt(sealed) == controlcipher.Decrypted(b"", b"")
    assert cipher.read_counter == 1
    assert cipher.write_counter == 1


def test_payload_over_0x4000_splits_into_fragments():
    plaintext = bytes((i * 11) & 0xff for i in range(0x4001))
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = cipher.encrypt(plaintext)

    assert len(sealed) == controlcipher.FRAGMENT_BYTES + \
        controlcipher.HEADER_BYTES + 1 + controlcipher.TAG_BYTES
    header, ciphertext, tag = frame_parts(sealed[:controlcipher.FRAGMENT_BYTES])
    assert struct.unpack("<H", header)[0] == 0x4000
    assert len(ciphertext) == 0x4000
    assert len(tag) == 16
    assert cipher.decrypt(sealed) == controlcipher.Decrypted(plaintext, b"")
    assert cipher.read_counter == 2
    assert cipher.write_counter == 2


def test_exact_payload_boundary_is_one_fragment():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = cipher.encrypt(b"b" * 0x4000)
    assert len(sealed) == controlcipher.FRAGMENT_BYTES
    assert cipher.write_counter == 1


def test_counter_advances_per_fragment_not_per_message():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    for size in (0x4000, 0x4000, 1):
        cipher.encrypt(b"z" * size)
    assert cipher.write_counter == 3


def test_counters_advance_independently():
    writer = controlcipher.ControlCipher(KEY, KEY)
    cipher = controlcipher.ControlCipher(KEY, KEY)

    cipher.encrypt(b"one")
    cipher.encrypt(b"two")
    cipher.decrypt(writer.encrypt(b"three"))

    assert cipher.write_counter == 2
    assert cipher.read_counter == 1


def test_frames_split_across_reads_remain_in_rest():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = cipher.encrypt(b"split across two reads")

    first = cipher.decrypt(sealed[:12])
    assert first == controlcipher.Decrypted(b"", sealed[:12])
    assert cipher.read_counter == 0

    second = cipher.decrypt(first.rest + sealed[12:])
    assert second == controlcipher.Decrypted(b"split across two reads", b"")
    assert cipher.read_counter == 1


def test_one_header_byte_is_a_remainder():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = cipher.encrypt(b"almost there")
    assert cipher.decrypt(sealed[:1]) == controlcipher.Decrypted(b"", sealed[:1])
    assert cipher.read_counter == 0


def test_concatenated_frames_all_decrypt():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = b"".join(
        cipher.encrypt(part) for part in (b"first", b"second", b"third"))
    assert cipher.decrypt(sealed) == controlcipher.Decrypted(b"firstsecondthird", b"")
    assert cipher.read_counter == 3


def test_interleaved_directions_keep_their_own_counters():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    out = cipher.encrypt(b"out one")
    out += cipher.encrypt(b"out two")

    assert cipher.decrypt(out).data == b"out oneout two"
    assert cipher.write_counter == 2
    assert cipher.read_counter == 2


def test_frames_only_decrypt_on_the_peers_side():
    device = controlcipher.ControlCipher(PEER_KEY, KEY)
    peer = controlcipher.ControlCipher(KEY, PEER_KEY)

    assert peer.decrypt(device.encrypt(b"from device")).data == b"from device"
    assert device.decrypt(peer.encrypt(b"from peer")).data == b"from peer"

    wrong = controlcipher.ControlCipher(WRONG_KEY, WRONG_KEY)
    with pytest.raises(crypto.AuthenticationError):
        wrong.decrypt(device.encrypt(b"from device"))


def test_tampered_ciphertext_is_rejected():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = bytearray(cipher.encrypt(b"tamper me"))
    sealed[5] ^= 0x80
    with pytest.raises(crypto.AuthenticationError):
        cipher.decrypt(bytes(sealed))
    assert cipher.read_counter == 0


def test_tampered_length_header_is_rejected():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = bytearray(cipher.encrypt(b"tamper me"))
    sealed[0] ^= 0x01
    with pytest.raises(crypto.AuthenticationError):
        cipher.decrypt(bytes(sealed))


def test_tampered_tag_is_rejected():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = bytearray(cipher.encrypt(b"tamper me"))
    sealed[-1] ^= 0x01
    with pytest.raises(crypto.AuthenticationError):
        cipher.decrypt(bytes(sealed))


def test_trailing_garbage_after_a_frame_is_remainder():
    cipher = controlcipher.ControlCipher(KEY, KEY)
    sealed = cipher.encrypt(b"done") + b"\x00\x00"
    result = cipher.decrypt(sealed)
    assert result.data == b"done"
    assert result.rest == b"\x00\x00"


def test_keys_must_be_32_bytes():
    with pytest.raises(crypto.CryptoError):
        controlcipher.ControlCipher(KEY, KEY[:-1])
    with pytest.raises(crypto.CryptoError):
        controlcipher.ControlCipher(b"", KEY)
    with pytest.raises(crypto.CryptoError):
        controlcipher.ControlCipher(KEY, KEY[:8])


def test_counter_exhaustion_does_not_wrap():
    assert controlcipher._advance(controlcipher.MAX_COUNTER - 1, "write") == \
        controlcipher.MAX_COUNTER
    with pytest.raises(crypto.CryptoError):
        controlcipher._advance(controlcipher.MAX_COUNTER, "read")


def test_decrypted_value_semantics():
    assert controlcipher.Decrypted(b"a", b"") == \
        controlcipher.Decrypted(b"a", b"")
    assert controlcipher.Decrypted(b"a", b"") != \
        controlcipher.Decrypted(b"a", b"rest")
    assert controlcipher.Decrypted(b"a", b"") != b"a"
    assert repr(controlcipher.Decrypted(b"abcd", b"xy")) == \
        "Decrypted(4, 2 rest)"
