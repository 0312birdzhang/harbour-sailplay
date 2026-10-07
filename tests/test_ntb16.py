import pytest

from carplay_proto import ntb16 as n
from carplay_proto.ntb16 import Ntb16Error


def test_constants_match_reference():
    assert n.NTH16_SIG == 0x484d434e
    assert n.NDP16_SIG == 0x304d434e
    assert n.NTH_LENGTH == 12
    assert n.NDP_LENGTH == 16
    assert n.DATAGRAM_INDEX == 28
    assert n.USB_PACKET_SIZE == 512
    assert n.MAX_DATAGRAM_BYTES == 0xffff - 28


def test_ntb16_layout():
    block = n.build(b"\x01\x02\x03", 1)
    assert len(block) == 28 + 3
    assert block[:4] == bytes([0x4e, 0x43, 0x4d, 0x48])       # NTH16 sig LE
    assert block[4:6] == bytes([12, 0])                        # nth length 12
    assert block[6:8] == bytes([1, 0])                         # sequence 1
    assert block[8:10] == bytes([31, 0])                       # block length 31
    assert block[10:12] == bytes([0, 0])                        # reserved
    assert block[12:16] == bytes([0x4e, 0x43, 0x4d, 0x30])      # NDP16 sig LE
    assert block[16:18] == bytes([16, 0])                      # ndp length 16
    assert block[20:22] == bytes([28, 0])                      # datagram index 28
    assert block[22:24] == bytes([3, 0])                       # datagram length 3
    assert block[28:] == b"\x01\x02\x03"


def test_build_roundtrip_single_frame():
    frame = b"\x33\x33\x00\x00\x00\x01\x86\xdd"
    block = n.build(frame, 7)
    assert n.parse(block) == [frame]


def test_build_roundtrip_at_datagram_index():
    frame = b"\x00" * 512
    block = n.build(frame, 0)
    assert n.parse(block) == [frame]


def test_build_rejects_empty_frame():
    with pytest.raises(Ntb16Error):
        n.build(b"", 0)


def test_build_rejects_oversized_frame():
    with pytest.raises(Ntb16Error):
        n.build(b"\x00" * (n.MAX_DATAGRAM_BYTES + 1), 0)


def test_build_rejects_bad_sequence():
    with pytest.raises(Ntb16Error):
        n.build(b"\x00", -1)
    with pytest.raises(Ntb16Error):
        n.build(b"\x00", 0x10000)


def test_build_pads_512_byte_boundary():
    """A block landing exactly on a USB packet boundary needs a pad byte."""
    frame = b"\x00" * (512 - 28)
    block = n.build(frame, 0)
    assert len(block) == 512 + 1
    assert block[-1] == 0
    assert n.parse(block) == [frame]


def test_build_no_pad_when_not_on_boundary():
    frame = b"\x00" * (512 - 28 + 1)
    block = n.build(frame, 0)
    assert len(block) == 512 + 1
    assert n.parse(block) == [frame]


def test_parse_roundtrip_preserves_sequence():
    block = n.build(b"payload", 0x1234)
    assert block[6:8] == bytes([0x34, 0x12])
    assert n.parse(block) == [b"payload"]


def test_parse_returns_empty_on_garbage():
    assert n.parse(b"\xde\xad\xbe\xef") == []
    assert n.parse(b"\x00\x00\x00\x00" + b"\x00" * 20) == []


def test_parse_returns_empty_on_short_block():
    assert n.parse(b"") == []
    assert n.parse(b"\x4e\x4c\x4d\x48" + b"\x00" * 5) == []


def test_parse_returns_empty_on_bad_ndp_signature():
    block = bytearray(n.build(b"payload", 0))
    block[12:16] = b"\x00\x00\x00\x00"
    assert n.parse(bytes(block)) == []


def test_parse_returns_empty_on_bad_ndp_length():
    block = bytearray(n.build(b"payload", 0))
    block[16:18] = bytes([0x00, 0x00])
    assert n.parse(bytes(block)) == []


def test_parse_rejects_oversized_datagram_index():
    block = bytearray(n.build(b"payload", 0))
    block[20:22] = bytes([0xff, 0xff])
    assert n.parse(bytes(block)) == []


def test_parse_rejects_oversized_datagram_length():
    block = bytearray(n.build(b"payload", 0))
    block[22:24] = bytes([0xff, 0xff])
    assert n.parse(bytes(block)) == []


def test_parse_with_explicit_offset_and_length():
    frame = b"abcdef"
    block = n.build(frame, 0)
    padded = b"\x00" * 10 + block + b"\x00" * 5
    assert n.parse(padded, offset=10, length=len(block)) == [frame]


def test_parse_ignores_trailing_bytes():
    frame = b"abcdef"
    block = n.build(frame, 0)
    assert n.parse(block + b"\x99\x99\x99", offset=0,
                   length=len(block)) == [frame]


def test_build_multi_two_frames():
    first = b"\x01\x02"
    second = b"\x03\x04\x05"
    block = n.build_multi([first, second], 3)
    assert n.parse(block) == [first, second]


def test_build_multi_single_frame_matches_build():
    frame = b"\x01\x02\x03"
    assert n.build_multi([frame], 5) == n.build(frame, 5)


def test_build_multi_lands_on_correct_datagram_index():
    block = n.build_multi([b"a", b"b"], 0)
    assert block[20:22] == bytes([32, 0])
    assert block[22:24] == bytes([1, 0])
    assert block[24:26] == bytes([33, 0])
    assert block[26:28] == bytes([1, 0])
    assert block[32:34] == b"ab"
    assert n.parse(block) == [b"a", b"b"]


def test_build_multi_rejects_empty():
    with pytest.raises(Ntb16Error):
        n.build_multi([], 0)


def test_build_multi_rejects_empty_frame():
    with pytest.raises(Ntb16Error):
        n.build_multi([b"", b"a"], 0)


def test_build_multi_rejects_oversized():
    with pytest.raises(Ntb16Error):
        n.build_multi([b"\x00" * 0x10000], 0)


def test_build_multi_rejects_oversized_block():
    with pytest.raises(Ntb16Error):
        n.build_multi([b"\x00" * (n.MAX_DATAGRAM_BYTES) * 2], 0)


def test_build_multi_rejects_bad_sequence():
    with pytest.raises(Ntb16Error):
        n.build_multi([b"a"], -1)


def test_build_multi_pads_512_boundary():
    frame = b"\x00" * (512 - 28)
    block = n.build_multi([frame], 0)
    assert len(block) == 513
    assert n.parse(block) == [frame]


def test_sequence_wraps_across_blocks():
    blocks = [n.build(b"payload", seq) for seq in (0xffff, 0, 1, 0x10000 - 1)]
    for block, seq in zip(blocks, (0xffff, 0, 1, 0xffff)):
        assert block[6:8] == bytes([seq & 0xff, (seq >> 8) & 0xff])
        assert n.parse(block) == [b"payload"]


def test_parse_roundtrip_random_sizes():
    import random
    random.seed(1234)
    for _ in range(50):
        size = random.randint(1, 2000)
        frame = bytes(random.randint(0, 255) for _ in range(size))
        sequence = random.randint(0, 0xffff)
        block = n.build(frame, sequence)
        assert n.parse(block) == [frame]
