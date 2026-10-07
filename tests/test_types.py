import pytest

from carplay_proto import types as t
from carplay_proto.types import CodecError


def test_void():
    assert t.encode(None, t.VOID) == b""
    assert t.decode(b"", t.VOID) is None
    with pytest.raises(CodecError):
        t.encode(1, t.VOID)
    with pytest.raises(CodecError):
        t.decode(b"\x00", t.VOID)


def test_bool_roundtrip():
    assert t.encode(True, t.BOOL) == b"\x01"
    assert t.encode(False, t.BOOL) == b"\x00"
    assert t.decode(b"\x01", t.BOOL) is True
    assert t.decode(b"\x00", t.BOOL) is False
    assert t.decode(b"\xff", t.BOOL) is True


@pytest.mark.parametrize("value,wire", [
    (0, b"\x00"),
    (1, b"\x01"),
    (127, b"\x7f"),
    (255, b"\xff"),
    (-128, b"\x80"),
    (-1, b"\xff"),
    (0, b"\x00"),
])
def test_u8_i8_sharing_a_byte(value, wire):
    unsigned = value if value >= 0 else None
    if unsigned is not None:
        assert t.encode(unsigned, t.U8) == wire
        assert t.decode(wire, t.U8) == unsigned
    signed = value if value <= 127 else None
    if signed is not None:
        assert t.encode(signed, t.I8) == wire
        assert t.decode(wire, t.I8) == signed


@pytest.mark.parametrize("value,kind", [
    (-1, "u8"), (256, "u8"), (128, "i8"),
    (-129, "i8"), (1.0, "u8"), ("1", "u8"),
    (True, "u8"),
])
def test_scalar_range_rejection(value, kind):
    with pytest.raises(CodecError):
        t.encode(value, t.U8 if kind == "u8" else t.I8)


def test_u16_i16_roundtrip():
    for value, wire in [(0, b"\x00\x00"), (1, b"\x00\x01"),
                        (0x1234, b"\x12\x34"), (0xffff, b"\xff\xff"),
                        (-1, b"\xff\xff"), (-0x1234, b"\xed\xcc"),
                        (-0x8000, b"\x80\x00")]:
        unsigned = value if value >= 0 else None
        if unsigned is not None:
            assert t.encode(unsigned, t.U16) == wire
            assert t.decode(wire, t.U16) == unsigned
        signed = value if value <= 0x7fff else None
        if signed is not None:
            assert t.encode(signed, t.I16) == wire
            assert t.decode(wire, t.I16) == signed


def test_u32_i32_roundtrip():
    for value, wire in [(0, b"\x00" * 4), (1, b"\x00\x00\x00\x01"),
                        (0x12345678, b"\x12\x34\x56\x78"),
                        (0xffffffff, b"\xff\xff\xff\xff"),
                        (-1, b"\xff\xff\xff\xff"),
                        (0x7fffffff, b"\x7f\xff\xff\xff")]:
        if value >= 0:
            assert t.encode(value, t.U32) == wire
            assert t.decode(wire, t.U32) == value
        signed = value if value <= 0x7fffffff else None
        if signed is not None:
            assert t.encode(signed, t.I32) == wire
            assert t.decode(wire, t.I32) == signed


def test_u64_roundtrip():
    cases = [(0, b"\x00" * 8), (1, b"\x00" * 7 + b"\x01"),
             (0x123456789abcdef0, b"\x12\x34\x56\x78\x9a\xbc\xde\xf0"),
             (0xffffffffffffffff, b"\xff" * 8)]
    for value, wire in cases:
        assert t.encode(value, t.U64) == wire
        assert t.decode(wire, t.U64) == value


@pytest.mark.parametrize("bad", [-1, 0x10000000000000000])
def test_u64_rejects_out_of_range(bad):
    with pytest.raises(CodecError):
        t.encode(bad, t.U64)


def test_u16_list_roundtrip():
    assert t.encode([], t.U16_LIST) == b""
    for values in [[0], [1, 0xffff], [0, 1, 2, 3, 4]]:
        wire = t.encode(values, t.U16_LIST)
        assert len(wire) == 2 * len(values)
        assert t.decode(wire, t.U16_LIST) == values


def test_u16_list_rejects_bad_input():
    with pytest.raises(CodecError):
        t.decode(b"\x01\x02\x03", t.U16_LIST)
    with pytest.raises(CodecError):
        t.encode([0x10000], t.U16_LIST)


def test_bytes_opaque_are_opaque():
    payload = bytes(range(20))
    for kind in (t.BYTES, t.OPAQUE, t.GROUP):
        assert t.encode(payload, kind) == payload
        assert t.decode(payload, kind) == payload


def test_string_is_nul_terminated():
    assert t.encode("hello", t.STRING) == b"hello\x00"
    assert t.decode(b"hello\x00", t.STRING) == "hello"
    assert t.decode(b"\x00", t.STRING) == ""


def test_string_rejects_embedded_nul_and_bad_input():
    with pytest.raises(CodecError):
        t.encode("a\x00b", t.STRING)
    with pytest.raises(CodecError):
        t.decode(b"not terminated", t.STRING)
    with pytest.raises(CodecError):
        t.decode(b"", t.STRING)


def test_string_utf8_roundtrip():
    assert t.decode(t.encode("\u5c0f\u8d64\u4e66", t.STRING), t.STRING) == "\u5c0f\u8d64\u4e66"


def test_string_list_roundtrip():
    values = ["a", "bc", ""]
    wire = t.encode(values, t.STRING_LIST)
    assert wire == b"a\x00bc\x00\x00"
    assert t.decode(wire, t.STRING_LIST) == values


def test_string_list_rejects_bad_termination():
    with pytest.raises(CodecError):
        t.decode(b"a\x00b", t.STRING_LIST)


@pytest.mark.parametrize("kind,expected", [
    (t.VOID, 0), (t.BOOL, 1), (t.U8, 1), (t.I8, 1),
    (t.U16, 2), (t.I16, 2), (t.U32, 4), (t.I32, 4), (t.U64, 8),
    (t.U16_LIST, None), (t.BYTES, None), (t.STRING, None),
    (t.STRING_LIST, None), (t.GROUP, None), (t.OPAQUE, None),
])
def test_size(kind, expected):
    assert t.size(kind) == expected


def test_every_type_roundtrips():
    samples = [
        (None, t.VOID),
        (True, t.BOOL),
        (7, t.U8),
        (-7, t.I8),
        (0x1234, t.U16),
        (-0x1234, t.I16),
        (0x12345678, t.U32),
        (-0x12345678, t.I32),
        (0x123456789abcdef0, t.U64),
        ([1, 2, 3], t.U16_LIST),
        (b"\x00\x01\x02", t.BYTES),
        (b"\x00\x01\x02", t.OPAQUE),
        ("device", t.STRING),
        (["zh", "en"], t.STRING_LIST),
    ]
    for value, kind in samples:
        assert t.decode(t.encode(value, kind), kind) == value
