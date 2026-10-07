"""Tests for the TLV8 codec."""

import pytest

from carplay_proto import tlv8


def test_type_constants_match_the_head_unit():
    assert tlv8.TYPE_METHOD == 0x00
    assert tlv8.TYPE_IDENTIFIER == 0x01
    assert tlv8.TYPE_SALT == 0x02
    assert tlv8.TYPE_PUBLIC_KEY == 0x03
    assert tlv8.TYPE_PROOF == 0x04
    assert tlv8.TYPE_ENCRYPTED_DATA == 0x05
    assert tlv8.TYPE_STATE == 0x06
    assert tlv8.TYPE_ERROR == 0x07
    assert tlv8.TYPE_SIGNATURE == 0x0a
    assert tlv8.ERROR_AUTHENTICATION == 2
    assert tlv8.SEPARATOR_TYPE == 0xff
    assert tlv8.MAX_FRAGMENT_BYTES == 255


def test_encode_two_items_is_literal():
    wire = tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, b"\x02"),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, b"abc"),
    ])
    assert wire == b"\x06\x01\x02\x03\x03abc"


def test_encode_same_type_twice_inserts_a_separator():
    wire = tlv8.encode([
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, b"ab"),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, b"cd"),
    ])
    assert wire == b"\x03\x02ab\xff\x00\x03\x02cd"


def test_encode_empty_list():
    assert tlv8.encode([]) == b""


def test_encode_empty_value():
    assert tlv8.encode([tlv8.Item(tlv8.TYPE_STATE, b"")]) == b"\x06\x00"


@pytest.mark.parametrize("size", [1, 254, 255, 256, 300, 510, 511, 512, 1000])
def test_round_trip_arbitrary_size(size):
    value = bytes((i * 7 + 3) & 0xff for i in range(size))
    wire = tlv8.encode([tlv8.Item(tlv8.TYPE_ENCRYPTED_DATA, value)])
    assert tlv8.decode(wire)[tlv8.TYPE_ENCRYPTED_DATA] == value


def test_single_fragment_uses_the_exact_length_byte():
    value = bytes(255)
    wire = tlv8.encode([tlv8.Item(tlv8.TYPE_SALT, value)])
    assert wire[:2] == bytes([tlv8.TYPE_SALT, 255])
    assert len(wire) == 257


def test_fragmented_value_is_reassembled_in_order():
    value = bytes(range(256)) * 4
    wire = tlv8.encode([tlv8.Item(tlv8.TYPE_PROOF, value)])
    assert tlv8.decode(wire)[tlv8.TYPE_PROOF] == value


def test_two_fragments_are_concatenated_not_replaced():
    value = bytes(256)
    wire = tlv8.encode([tlv8.Item(tlv8.TYPE_PROOF, value)])
    # [type][255][255 bytes][type][1][1 byte]
    assert len(wire) == 2 + 255 + 2 + 1
    assert tlv8.decode(wire)[tlv8.TYPE_PROOF] == value


def test_full_fragment_followed_by_a_shorter_one_keeps_both():
    long_value = bytes(300)
    wire = tlv8.encode([tlv8.Item(tlv8.TYPE_PROOF, long_value)])
    assert len(tlv8.decode(wire)[tlv8.TYPE_PROOF]) == 300


def test_short_fragment_then_same_type_again_is_a_new_value():
    wire = tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, b"\x02"),
        tlv8.Item(tlv8.TYPE_STATE, b"\x04"),
    ])
    # The 1-byte fragment is not a full fragment, so the second state record
    # starts a new value instead of concatenating.
    assert tlv8.decode(wire)[tlv8.TYPE_STATE] == b"\x04"


def test_separator_record_is_not_treated_as_a_value():
    wire = b"\x03\x02ab\xff\x00\x03\x02cd"
    decoded = tlv8.decode(wire)
    assert decoded[tlv8.TYPE_PUBLIC_KEY] == b"cd"


@pytest.mark.parametrize("cut", [0, 1, 2, 3, 4, 5, 10])
def test_truncated_buffer_never_raises(cut):
    wire = tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, b"\x02"),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, b"abcde"),
    ])
    decoded = tlv8.decode(wire[:cut])
    assert isinstance(decoded, dict)
    if cut >= 3:
        assert decoded.get(tlv8.TYPE_STATE) == b"\x02"


def test_decode_empty_buffer():
    assert tlv8.decode(b"") == {}


def test_decode_drops_a_fragment_that_runs_past_the_end():
    wire = tlv8.encode([tlv8.Item(tlv8.TYPE_SALT, b"\x01\x02\x03")])
    assert tlv8.decode(wire[:-1]) == {}
    assert tlv8.decode(wire) == {tlv8.TYPE_SALT: b"\x01\x02\x03"}


def test_later_duplicate_type_overwrites():
    decoded = tlv8.decode(tlv8.encode([
        tlv8.Item(tlv8.TYPE_IDENTIFIER, b"first"),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, b"key"),
        tlv8.Item(tlv8.TYPE_IDENTIFIER, b"second"),
    ]))
    assert decoded[tlv8.TYPE_IDENTIFIER] == b"second"
    assert decoded[tlv8.TYPE_PUBLIC_KEY] == b"key"


def test_item_copies_its_value():
    value = bytearray(b"abc")
    item = tlv8.Item(tlv8.TYPE_PUBLIC_KEY, value)
    value[0] = 0x99
    assert item.value == b"abc"


def test_item_equality():
    assert tlv8.Item(0x06, b"\x02") == tlv8.Item(0x06, b"\x02")
    assert tlv8.Item(0x06, b"\x02") != tlv8.Item(0x06, b"\x04")
    assert tlv8.Item(0x06, b"\x02") != tlv8.Item(0x03, b"\x02")
    assert tlv8.Item(0x06, b"\x02") != (0x06, b"\x02")


def test_item_accepts_an_iterable_value():
    item = tlv8.Item(tlv8.TYPE_STATE, (2,))
    assert item.value == b"\x02"


def test_repr_names_the_type_and_size():
    assert "0x06" in repr(tlv8.Item(0x06, b"\x02"))
    assert "1 byte" in repr(tlv8.Item(0x06, b"\x02"))


def test_pairing_shape_survives_a_round_trip():
    """The shape PairVerify m2 sends: state, public key, then a long sealed
    blob that must be split across fragments."""
    sealed = bytes(range(256)) * 3
    wire = tlv8.encode([
        tlv8.Item(tlv8.TYPE_STATE, b"\x02"),
        tlv8.Item(tlv8.TYPE_PUBLIC_KEY, b"\x11" * 32),
        tlv8.Item(tlv8.TYPE_ENCRYPTED_DATA, sealed),
    ])
    decoded = tlv8.decode(wire)
    assert decoded == {
        tlv8.TYPE_STATE: b"\x02",
        tlv8.TYPE_PUBLIC_KEY: b"\x11" * 32,
        tlv8.TYPE_ENCRYPTED_DATA: sealed,
    }
