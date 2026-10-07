import pytest

from carplay_proto.wire import (
    HEADER_BYTES, MAX_BODY_BYTES, MAX_FRAME_BYTES, MAX_PARAM_BYTES,
    MAX_PARAM_PAYLOAD_BYTES, Frame, Framer, Parameter, ProtocolError,
    encode_frame, encode_param, encode_params, parse_params,
)


def test_constants_match_reference():
    assert HEADER_BYTES == 6
    assert MAX_FRAME_BYTES == 0xffff
    assert MAX_BODY_BYTES == 0xffff - 6
    assert MAX_PARAM_BYTES == 0xffff
    assert MAX_PARAM_PAYLOAD_BYTES == 0xffff - 4


def test_encode_frame_layout():
    frame = encode_frame(0x4300, bytes([0, 4, 0, 0]))
    assert frame == bytes([0x40, 0x40, 0x00, 0x0a, 0x43, 0x00, 0, 4, 0, 0])
    assert len(frame) == HEADER_BYTES + 4


def test_encode_frame_empty_body():
    assert encode_frame(0, b"") == bytes([0x40, 0x40, 0x00, 0x06, 0, 0])


def test_encode_param_layout():
    assert encode_param(0, b"\x01") == bytes([0x00, 0x05, 0x00, 0x00, 0x01])
    assert encode_param(0x7fff, b"\x03\x04") == bytes(
        [0x00, 0x06, 0x7f, 0xff, 0x03, 0x04])


def test_frame_roundtrip():
    frame = Frame(0x4301, bytes([0, 5, 0, 0, 1]))
    assert frame.encoded() == bytes([0x40, 0x40, 0x00, 0x0b, 0x43, 0x01,
                                     0, 5, 0, 0, 1])
    assert frame.message_id == 0x4301
    assert frame.body == bytes([0, 5, 0, 0, 1])


def test_parameter_roundtrip():
    param = Parameter(0x4300, b"\x01\x02\x03")
    encoded = encode_param(param.id, param.payload)
    assert encoded == bytes([0x00, 0x07, 0x43, 0x00, 0x01, 0x02, 0x03])
    (decoded,) = parse_params(encoded)
    assert decoded == param


def test_parse_params_rejects_truncated_header():
    with pytest.raises(ProtocolError):
        parse_params(b"\x00\x05\x00")


def test_parse_params_rejects_short_length():
    with pytest.raises(ProtocolError):
        parse_params(b"\x00\x03\x00\x00\x00")


def test_parse_params_rejects_oversized_length():
    with pytest.raises(ProtocolError):
        parse_params(b"\x00\x06\x00\x00\x01")


def test_parse_params_empty_body():
    assert parse_params(b"") == []


def test_frame_rejects_bad_ids():
    with pytest.raises(ProtocolError):
        Frame(-1, b"")
    with pytest.raises(ProtocolError):
        Frame(0x10000, b"")
    with pytest.raises(ProtocolError):
        Parameter(-1, b"")
    with pytest.raises(ProtocolError):
        Parameter(0x10000, b"")


def test_frame_rejects_oversized_body():
    with pytest.raises(ProtocolError):
        Frame(1, b"\x00" * (MAX_BODY_BYTES + 1))
    with pytest.raises(ProtocolError):
        Parameter(1, b"\x00" * (MAX_PARAM_PAYLOAD_BYTES + 1))


def test_frame_equality():
    assert Frame(1, b"abc") == Frame(1, b"abc")
    assert Frame(1, b"abc") != Frame(1, b"abd")
    assert Frame(1, b"abc") != Frame(2, b"abc")


def test_body_preserves_ownership():
    body = bytearray([1, 2, 3])
    frame = Frame(1, body)
    body[0] = 9
    assert frame.body == b"\x01\x02\x03"
    param = Parameter(1, body)
    body[1] = 9
    assert param.payload == b"\x09\x02\x03"


def test_framer_accepts_fragmented_and_concatenated_frames():
    first = Frame(0x4300, bytes([0, 4, 0, 0]))
    second = Frame(0x4301, bytes([0, 5, 0, 0, 1]))
    stream = first.encoded() + second.encoded()

    framer = Framer()
    assert framer.offer(stream[:3]) == []
    assert framer.offer(stream[3:]) == [first, second]


def test_framer_handles_arbitrary_chunking():
    first = Frame(0x4300, bytes([0, 4, 0, 0]))
    second = Frame(0x4301, bytes([0, 5, 0, 0, 1]))
    stream = first.encoded() + second.encoded()

    framer = Framer()
    collected = []
    for i in range(len(stream)):
        collected += framer.offer(stream[i:i + 1])
    assert collected == [first, second]
    assert framer.pending() == 0


def test_framer_discards_leading_garbage():
    frame = Frame(0x4300, bytes([0, 4, 0, 0]))
    framer = Framer()
    assert framer.offer(b"\xde\xad\xbe\xef\x00") == []
    assert framer.offer(frame.encoded()) == [frame]


def test_framer_rejects_invalid_length_and_resyncs():
    good = Frame(0x4300, bytes([0, 4, 0, 0]))
    garbage = bytes([0x40, 0x40, 0x00, 0x02])
    framer = Framer()
    assert framer.offer(garbage) == []
    assert framer.offer(good.encoded()) == [good]


def test_framer_raises_on_buffer_overflow():
    framer = Framer(max_buffer=10)
    with pytest.raises(ProtocolError):
        framer.offer(b"\x40" * 40)


def test_framer_reset():
    framer = Framer()
    framer.offer(b"\x40\x40\x00\x0a\x43")
    assert framer.pending() == 5
    framer.reset()
    assert framer.pending() == 0


def test_encode_params_enforces_body_limit():
    chunk = encode_param(1, b"\x00" * MAX_PARAM_PAYLOAD_BYTES)
    with pytest.raises(ProtocolError):
        encode_params([Parameter(1, b"\x00"), Parameter(1, chunk[4:])])


def test_repeated_parameter_ids_preserve_order():
    params = [Parameter(0, b"\x01"), Parameter(0, b"\x02"),
              Parameter(0x7fff, b"\x03\x04")]
    encoded = encode_params(params)
    decoded = parse_params(encoded)
    assert [p.id for p in decoded] == [0, 0, 0x7fff]
    assert decoded[0].payload == b"\x01"
    assert decoded[1].payload == b"\x02"
    assert decoded[2].payload == b"\x03\x04"


def test_frame_parameters_property():
    frame = Frame(0x0d01, bytes([0x00, 0x06, 0x00, 0x00, 0x00, 0x01]))
    assert [p.id for p in frame.parameters()] == [0]
    assert frame.parameters()[0].payload == b"\x00\x01"
