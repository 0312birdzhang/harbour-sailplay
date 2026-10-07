import pytest

from carplay_proto import usbmux as u
from carplay_proto.usbmux import FrameDecoder, TransportError


def test_constants_match_reference():
    assert u.HEADER_BYTES == 16
    assert u.MAX_FRAME_BYTES == 65536
    assert u.VERSION_MESSAGE_BYTES == 20
    assert u.USBMUX_VERSION == 2
    assert u.SETUP_VALUE == 0x07
    assert u.PROTOCOL_VERSION == 0
    assert u.PROTOCOL_SETUP == 2
    assert u.PROTOCOL_TCP == 6
    assert u.TCP_HEADER_BYTES == 20
    assert u.TCP_WINDOW_FIELD == 512
    assert u.TCP_SYN == 0x02
    assert u.TCP_RST == 0x04
    assert u.TCP_ACK == 0x10
    assert u.LOCKDOWN_PORT == 62078


def test_version_handshake_is_a_20_byte_message():
    message = u.build_version_handshake()
    assert len(message) == 20
    assert message[:12] == bytes([
        0, 0, 0, 0,              # protocol = 0
        20, 0, 0, 0,             # length = 20
        2, 0, 0, 0,              # version = 2
    ])
    assert message[12:] == b"\0" * 8


def test_setup_frame_layout():
    frame = u.build_setup()
    assert len(frame) == 17
    assert frame[:16] == bytes([
        2, 0, 0, 0,                # protocol = SETUP
        17, 0, 0, 0,               # length = 17
        0xce, 0xfa, 0xed, 0xfe,    # magic 0xfeedface, little-endian
        0, 0, 0, 0,                # seq = 0, ack = 0
    ])
    assert frame[16] == 0x07


def test_frame_layout_and_roundtrip():
    frame = u.build_frame(u.PROTOCOL_TCP, b"\x01\x02\x03", seq=5, ack=7)
    assert len(frame) == 19
    protocol, length, word8, seq, ack, payload, end = u.parse(frame)
    assert protocol == u.PROTOCOL_TCP
    assert length == 19
    assert word8 == 0xfeedface
    assert seq == 5
    assert ack == 7
    assert payload == b"\x01\x02\x03"
    assert end == 19


def test_parse_rejects_truncated_header():
    with pytest.raises(TransportError):
        u.parse(b"\x00" * 15)


def test_parse_rejects_short_length():
    bad = bytearray(b"\x00" * 16)
    bad[4:8] = bytes([12, 0, 0, 0])
    with pytest.raises(TransportError):
        u.parse(bytes(bad))


def test_parse_rejects_oversized_length():
    bad = bytearray(b"\x00" * 16)
    bad[4:8] = bytes([0x00, 0x02, 0x00, 0x00])
    with pytest.raises(TransportError):
        u.parse(bytes(bad))


def test_parse_rejects_truncated_payload():
    frame = u.build_frame(u.PROTOCOL_TCP, b"\x01\x02\x03")
    with pytest.raises(TransportError):
        u.parse(frame[:-1])


def test_frame_roundtrip_preserves_seq_and_ack():
    for seq in (0, 1, 0x7fff, 0xffff):
        for ack in (0, 0x1234, 0xffff):
            frame = u.build_frame(6, b"payload", seq=seq, ack=ack)
            protocol, length, word8, got_seq, got_ack, payload, end = u.parse(frame)
            assert protocol == 6
            assert length == len(frame)
            assert word8 == 0xfeedface
            assert got_seq == seq
            assert got_ack == ack
            assert payload == b"payload"
            assert end == len(frame)


def test_frame_rejects_oversized_payload():
    with pytest.raises(TransportError):
        u.build_frame(6, b"\x00" * (u.MAX_FRAME_BYTES - u.HEADER_BYTES + 1))


def test_tcp_header_layout():
    tcp = u.build_tcp_header(1, 62078, 1, 0, u.TCP_SYN, 0)
    assert len(tcp) == 20
    assert tcp[0:2] == bytes([1, 0])           # source port 1
    assert tcp[2:4] == bytes([62078 & 0xff, 62078 >> 8])
    assert tcp[4:8] == bytes([1, 0, 0, 0])     # sequence 1
    assert tcp[8:12] == b"\x00" * 4            # ack 0
    assert tcp[12] == (20 // 4) << 4           # data offset 5
    assert tcp[13] == u.TCP_SYN                # flags
    assert tcp[14:16] == bytes([512 & 0xff, 512 >> 8])  # window 512
    assert tcp[16:20] == b"\x00" * 4           # checksum + urgent, zero


def test_tcp_frame_roundtrip():
    frame = u.build_tcp_frame(
        source_port=1, destination_port=u.LOCKDOWN_PORT,
        sequence=1, acknowledgement=0, flags=u.TCP_SYN, seq=3, ack=4)
    protocol, length, word8, mux_seq, mux_ack, payload, end = u.parse(frame)
    assert protocol == u.PROTOCOL_TCP
    assert word8 == 0xfeedface
    assert mux_seq == 3
    assert mux_ack == 4

    source, dest, seq, ack, flags, tcp_payload, tcp_end = u.parse_tcp(frame)
    assert source == 1
    assert dest == u.LOCKDOWN_PORT
    assert seq == 1
    assert ack == 0
    assert flags == u.TCP_SYN
    assert tcp_payload == payload
    assert tcp_end == end


def test_tcp_frame_carries_payload():
    data = b"hello world"
    frame = u.build_tcp_frame(1, u.LOCKDOWN_PORT, 5, 0, u.TCP_ACK,
                              payload=data)
    source, dest, seq, ack, flags, segment, end = u.parse_tcp(frame)
    assert source == 1
    assert dest == u.LOCKDOWN_PORT
    assert seq == 5
    assert ack == 0
    assert flags == u.TCP_ACK
    assert len(segment) == u.TCP_HEADER_BYTES + len(data)
    assert segment[u.TCP_HEADER_BYTES:] == data
    assert end == len(frame)


def test_parse_tcp_rejects_non_tcp_protocol():
    frame = u.build_frame(u.PROTOCOL_VERSION, b"x")
    with pytest.raises(TransportError):
        u.parse_tcp(frame)


def test_parse_tcp_rejects_bad_magic():
    bad = bytearray(u.build_frame(u.PROTOCOL_TCP, b"x"))
    bad[8:12] = b"\x00\x00\x00\x00"
    with pytest.raises(TransportError):
        u.parse_tcp(bytes(bad))


def test_parse_tcp_rejects_truncated_tcp_header():
    frame = u.build_frame(u.PROTOCOL_TCP, b"\x01\x02")
    with pytest.raises(TransportError):
        u.parse_tcp(frame)


def test_tcp_flags_cover_the_three_wires():
    assert u.TCP_FIN & (u.TCP_SYN | u.TCP_RST | u.TCP_ACK) == 0
    assert u.TCP_SYN & (u.TCP_RST | u.TCP_ACK) == 0
    assert u.TCP_RST & u.TCP_ACK == 0


def test_decoder_splits_multiple_frames_in_one_chunk():
    decoder = FrameDecoder()
    first = u.build_frame(u.PROTOCOL_TCP, b"abc", seq=1)
    second = u.build_frame(u.PROTOCOL_TCP, b"defg", seq=2)
    frames = decoder.feed(first + second)
    assert len(frames) == 2
    assert frames[0][4] == b"abc"
    assert frames[1][4] == b"defg"


def test_decoder_buffers_partial_frames():
    decoder = FrameDecoder()
    frame = u.build_frame(u.PROTOCOL_TCP, b"abc")
    assert decoder.feed(frame[:10]) == []
    assert decoder.pending() == 10
    rest = decoder.feed(frame[10:])
    assert len(rest) == 1
    assert rest[0][4] == b"abc"
    assert decoder.pending() == 0


def test_decoder_rejects_bad_length():
    decoder = FrameDecoder()
    bad = bytearray(b"\x00" * 16)
    bad[4:8] = bytes([5, 0, 0, 0])
    with pytest.raises(TransportError):
        decoder.feed(bytes(bad))


def test_decoder_handles_empty_feeds():
    decoder = FrameDecoder()
    assert decoder.feed(b"") == []
    assert decoder.pending() == 0


def test_version_handshake_parses_as_a_frame():
    message = u.build_version_handshake()
    protocol, length, word8, seq, ack, payload, end = u.parse(message)
    assert protocol == u.PROTOCOL_VERSION
    assert length == 20
    assert word8 == u.USBMUX_VERSION
    assert payload == b"\x00" * 4
    assert end == 20


def test_tcp_syn_handshake_sequence():
    """Mirrors the three-wire connect: SYN, SYN+ACK, ACK."""
    syn = u.build_tcp_frame(1, u.LOCKDOWN_PORT, 1, 0, u.TCP_SYN)
    source, dest, seq, ack, flags, segment, end = u.parse_tcp(syn)
    assert source == 1
    assert dest == u.LOCKDOWN_PORT
    assert seq == 1
    assert ack == 0
    assert flags == u.TCP_SYN

    reply = u.build_tcp_frame(u.LOCKDOWN_PORT, 1, 1, 2,
                              u.TCP_SYN | u.TCP_ACK)
    source, dest, seq, ack, flags, segment, end = u.parse_tcp(reply)
    assert source == u.LOCKDOWN_PORT
    assert dest == 1
    assert flags == (u.TCP_SYN | u.TCP_ACK)
    assert ack == 2

    final = u.build_tcp_frame(1, u.LOCKDOWN_PORT, 2, 2, u.TCP_ACK)
    source, dest, seq, ack, flags, segment, end = u.parse_tcp(final)
    assert flags == u.TCP_ACK
    assert seq == 2
    assert ack == 2
