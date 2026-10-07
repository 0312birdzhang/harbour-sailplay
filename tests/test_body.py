import pytest

from carplay_proto import types as t
from carplay_proto.body import BodyBuilder, BodyReader, Field, SchemaError


def bld(message_id=0x0d01, fields=(), validate=False):
    """A raw builder; chain the setters, then ``build()`` yields a Frame."""
    return BodyBuilder(fields=fields, message_id=message_id,
                       validate=validate)


def test_generic_builder_constructs_nested_body():
    frame = bld().u16(0, 1).group(4, lambda b: b.u32(0, 7).u8(1, 2))\
        .build()
    assert frame.message_id == 0x0d01

    reader = BodyReader.of(frame)
    assert reader.u16(0) == 1
    assert reader.group(4).u32(0) == 7
    assert reader.group(4).u8(1) == 2


def test_group_payload_is_a_nested_parameter_list():
    body = bld().group(4, lambda b: b.u32(0, 7).u8(1, 2)).build().body
    # outer: [00 11 00 04] then the inner parameter list
    assert body[:4] == bytes([0x00, 0x11, 0x00, 0x04])
    inner = body[4:]
    assert inner == bytes([0x00, 0x08, 0x00, 0x00, 0, 0, 0, 7,
                           0x00, 0x05, 0x00, 0x01, 0x02])
    assert len(inner) == 13


def test_nested_group_ids_restart_from_zero():
    reader = BodyReader.of(
        bld().u16(0, 42).group(4, lambda b: b.u32(0, 7).u8(1, 2)).build())
    assert reader.u16(0) == 42
    assert reader.optional_u8(1) is None
    assert reader.group(4).u32(0) == 7
    assert reader.group(4).u8(1) == 2


def test_repeated_ids_are_preserved():
    reader = BodyReader.of(bld().u8(0, 1).u8(0, 2).u8(0, 3).build())
    assert [p.payload for p in reader.all(0)] == [b"\x01", b"\x02", b"\x03"]
    assert reader.u8(0) == 1


def test_builder_rejects_repeated_non_repeatable():
    with pytest.raises(SchemaError):
        BodyBuilder(fields=[Field(0, "a", t.U8)], message_id=1,
                    validate=True).u8(0, 1).u8(0, 2).build()


def test_builder_allows_repeated_repeatable():
    frame = (BodyBuilder(fields=[Field(0, "a", t.STRING, repeatable=True)],
                         message_id=1, validate=True)
             .string(0, "a").string(0, "b").build())
    reader = BodyReader.of(frame)
    assert [p.payload for p in reader.all(0)] == [b"a\x00", b"b\x00"]


def test_builder_rejects_unknown_id():
    with pytest.raises(SchemaError):
        BodyBuilder(fields=[Field(0, "a", t.U8)], message_id=1,
                    validate=True).u8(9, 1).build()


def test_builder_rejects_wrong_type():
    with pytest.raises(SchemaError):
        BodyBuilder(fields=[Field(0, "a", t.U16)], message_id=1,
                    validate=True).u8(0, 1).build()


def test_builder_requires_required_fields():
    with pytest.raises(SchemaError):
        BodyBuilder(fields=[Field(0, "a", t.U8, required=True)],
                    message_id=1, validate=True).build()


def test_builder_satisfied_by_required_field():
    frame = (BodyBuilder(fields=[Field(0, "a", t.U8, required=True)],
                         message_id=1, validate=True)
             .u8(0, 1).build())
    assert BodyReader.of(frame).u8(0) == 1


def test_builder_accepts_opaque_when_declared_opaque():
    frame = (BodyBuilder(fields=[Field(0, "a", t.OPAQUE)], message_id=1,
                         validate=True)
             .raw(0, b"\xde\xad\xbe\xef").build())
    assert BodyReader.of(frame).raw(0) == b"\xde\xad\xbe\xef"


def test_optional_helpers_omit_none():
    reader = BodyReader.of(bld()
                           .optional_u8(1, None).optional_u8(2, 7)
                           .optional_void(3, False).build())
    assert reader.optional_u8(1) is None
    assert reader.optional_u8(2) == 7
    assert reader.optional_void(3) is False


def test_optional_helpers_emit_when_present():
    reader = BodyReader.of(bld()
                           .optional_u8(1, 3).optional_string(2, "x")
                           .optional_void(3, True).optional_bytes(4, b"z")
                           .build())
    assert reader.optional_u8(1) == 3
    assert reader.optional_string(2) == "x"
    assert reader.optional_void(3) is True
    assert reader.optional_raw(4) == b"z"


def test_void_requires_empty_payload():
    assert BodyReader.of(bld().void(0).build()).void(0) is True
    with pytest.raises(ValueError):
        BodyReader.of(bld().u8(0, 1).build()).void(0)


def test_reader_of_frame_and_of_body_agree():
    frame = bld().string(0, "hello").u32(1, 99).build()
    from_frame = BodyReader.of(frame)
    from_bytes = BodyReader.of_body(frame.body)
    assert from_frame.string(0) == from_bytes.string(0)
    assert from_frame.u32(1) == from_bytes.u32(1)
    assert len(from_frame) == len(from_bytes)


def test_reader_optional_accessors():
    reader = BodyReader.of(bld().string(0, "x").build())
    assert reader.optional_string(0) == "x"
    assert reader.optional_string(1) is None
    assert reader.optional_u32(1) is None
    assert reader.optional_bool(2) is None
    assert reader.optional_group(3) is None
    assert reader.optional_raw(4) is None
    assert reader.optional_void(5) is False


def test_reader_require_missing_raises():
    with pytest.raises(ValueError):
        BodyReader.of(bld().build()).u8(0)


def test_reader_rejects_wrong_sited_payload():
    reader = BodyReader.of(bld().u32(0, 1).build())
    with pytest.raises(ValueError):
        reader.u16(0)


def test_bool_reads_nonzero_as_true():
    assert BodyReader.of(bld().u8(0, 0xff).build()).bool(0) is True
    assert BodyReader.of(bld().bool(0, False).build()).bool(0) is False


def test_group_reader_is_recursive():
    reader = BodyReader.of(bld()
                           .group(1, lambda b: b.group(2,
                                                        lambda c: c.u8(0, 5)))
                           .build())
    assert reader.group(1).group(2).u8(0) == 5


def test_reader_length_and_iteration():
    reader = BodyReader.of(bld().u8(0, 1).u8(1, 2).build())
    assert len(reader) == 2
    assert [p.id for p in reader] == [0, 1]
    assert not reader.is_empty()
    assert BodyReader.of_body(b"").is_empty()


def test_reader_has_and_first():
    reader = BodyReader.of(bld().u8(0, 1).build())
    assert reader.has(0)
    assert not reader.has(1)
    assert reader.first(0).payload == b"\x01"
    assert reader.first(1) is None


def test_all_scalar_helpers_roundtrip_through_builder():
    reader = BodyReader.of(bld()
                           .u8(0, 1).i8(1, -2).bool(2, True)
                           .u16(3, 300).i16(4, -300)
                           .u32(5, 0x12345678).i32(6, -0x12345678)
                           .u64(7, 0x123456789abcdef0)
                           .string(8, "text").strings(9, ["a", "b"])
                           .u16list(10, [1, 2]).bytes(11, b"\x01\x02")
                           .void(12).build())
    assert reader.u8(0) == 1
    assert reader.i8(1) == -2
    assert reader.bool(2) is True
    assert reader.u16(3) == 300
    assert reader.i16(4) == -300
    assert reader.u32(5) == 0x12345678
    assert reader.i32(6) == -0x12345678
    assert reader.u64(7) == 0x123456789abcdef0
    assert reader.string(8) == "text"
    assert reader.strings(9) == ["a", "b"]
    assert reader.u16list(10) == [1, 2]
    assert reader.raw(11) == b"\x01\x02"
    assert reader.void(12) is True


def test_optional_typed_helpers_roundtrip():
    reader = BodyReader.of(bld()
                           .u16(0, 1).i16(1, -2).u32(2, 3).i32(3, -4)
                           .u64(4, 5).build())
    assert reader.optional_u16(0) == 1
    assert reader.optional_i16(1) == -2
    assert reader.optional_u32(2) == 3
    assert reader.optional_i32(3) == -4
    assert reader.optional_u64(4) == 5
    assert reader.optional_i8(6) is None


def test_field_rejects_bad_id():
    with pytest.raises(ValueError):
        Field(0x10000, "x", t.U8)


def test_builder_group_uses_child_schema_when_validating():
    fields = [Field(0, "outer", t.GROUP, children=[
        Field(0, "inner", t.U8),
    ])]
    with pytest.raises(SchemaError):
        BodyBuilder(fields=fields, message_id=1, validate=True)\
            .group(0, lambda b: b.u16(0, 1)).build()


def test_builder_group_accepts_valid_child():
    fields = [Field(0, "outer", t.GROUP, children=[
        Field(0, "inner", t.U8),
    ])]
    frame = BodyBuilder(fields=fields, message_id=1, validate=True)\
        .group(0, lambda b: b.u8(0, 9)).build()
    assert BodyReader.of(frame).group(0).u8(0) == 9


def test_builder_without_message_id_raises():
    with pytest.raises(SchemaError):
        BodyBuilder().build()
    frame = BodyBuilder().build(message_id=0x4300)
    assert frame.message_id == 0x4300


def test_builder_ignores_schema_when_validate_false():
    frame = BodyBuilder(fields=[Field(0, "a", t.U8)], message_id=1)\
        .u8(99, 1).build()
    assert BodyReader.of(frame).u8(99) == 1


def test_builder_entry_order_is_insertion_order():
    reader = BodyReader.of(bld().u8(3, 1).u8(1, 2).u8(2, 3).build())
    assert [p.id for p in reader] == [3, 1, 2]
