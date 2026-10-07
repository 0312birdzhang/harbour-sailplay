"""NTB16 (16-bit transfer block) codec for the iPhone NCM data link.

One NTH16 header, one NDP16 table with one datagram. No NTB32, alignment
padding, CRC, or NCM control-plane handling.
"""

import struct


NTH16_SIG = 0x484d434e
NDP16_SIG = 0x304d434e
NTH_LENGTH = 12
NDP_LENGTH = 16
DATAGRAM_INDEX = 28
USB_PACKET_SIZE = 512
MAX_DATAGRAM_BYTES = 0xffff - DATAGRAM_INDEX


class Ntb16Error(ValueError):
    pass


def build(frame, sequence):
    """Wrap one Ethernet frame in one NTB16 block."""
    if not frame:
        raise Ntb16Error("frame must not be empty")
    if len(frame) > MAX_DATAGRAM_BYTES:
        raise Ntb16Error("frame exceeds the NTB16 length field")
    if not 0 <= sequence <= 0xffff:
        raise Ntb16Error("sequence must fit in u16")

    block_length = DATAGRAM_INDEX + len(frame)
    block = bytearray(block_length)
    struct.pack_into("<IHHH", block, 0, NTH16_SIG, NTH_LENGTH, sequence,
                     block_length)
    struct.pack_into("<IHHHHH", block, 12, NDP16_SIG, NDP_LENGTH, 0,
                     DATAGRAM_INDEX, len(frame), 0)
    block[DATAGRAM_INDEX:] = frame

    if block_length % USB_PACKET_SIZE == 0:
        block.append(0)
    return bytes(block)


def parse(block, offset=0, length=None):
    """Extract the Ethernet frames carried by one NTB16 block.

    Returns an empty list on wire garbage instead of raising, and skips
    malformed entries on a bounds failure.
    """
    if length is None:
        length = len(block) - offset
    end = offset + length
    if length < NTH_LENGTH:
        return []

    sig = struct.unpack_from("<I", block, offset)[0]
    if sig != NTH16_SIG:
        return []

    header_length = struct.unpack_from("<H", block, offset + 10)[0]
    ndp_offset = offset + (header_length if header_length else NTH_LENGTH)

    datagrams = []
    hops = 0
    max_hops = max(1, length // 4)
    while ndp_offset and hops < max_hops:
        if ndp_offset < offset or ndp_offset + 12 > end:
            break
        ndp_sig = struct.unpack_from("<I", block, ndp_offset)[0] & 0x00ffffff
        if ndp_sig != NDP16_SIG & 0x00ffffff:
            break
        ndp_length = struct.unpack_from("<H", block, ndp_offset + 4)[0]
        next_ndp = struct.unpack_from("<H", block, ndp_offset + 6)[0]

        entry = ndp_offset + 8
        ndp_end = min(ndp_offset + ndp_length, end)
        while entry + 4 <= ndp_end:
            index, datagram_length = struct.unpack_from("<HH", block, entry)
            if not index or not datagram_length:
                break
            start = offset + index
            stop = start + datagram_length
            if offset <= start and start <= end and stop <= end:
                datagrams.append(bytes(block[start:stop]))
            entry += 4

        ndp_offset = 0 if not next_ndp else offset + next_ndp
        hops += 1

    return datagrams


def build_multi(frames, sequence):
    """Wrap several Ethernet frames in one NTB16 block.

    The NDP16 table reserves 4 bytes after the last entry, so a single-frame
    block lands on ``DATAGRAM_INDEX == 28``.
    """
    if not frames:
        raise Ntb16Error("at least one frame is required")
    if not 0 <= sequence <= 0xffff:
        raise Ntb16Error("sequence must fit in u16")
    for frame in frames:
        if not frame:
            raise Ntb16Error("frame must not be empty")
        if len(frame) > 0xffff:
            raise Ntb16Error("frame exceeds the NDP16 length field")

    ndp_length = NTH_LENGTH + 4 * len(frames)
    datagram_index = NTH_LENGTH + ndp_length
    if datagram_index > 0xffff:
        raise Ntb16Error("block would exceed u16")

    block_length = datagram_index + sum(len(frame) for frame in frames)
    if block_length > 0xffff:
        raise Ntb16Error("block length exceeds u16")

    block = bytearray(block_length)
    struct.pack_into("<IHHH", block, 0, NTH16_SIG, NTH_LENGTH, sequence,
                     block_length)
    struct.pack_into("<IHH", block, NTH_LENGTH, NDP16_SIG, ndp_length, 0)

    offset = datagram_index
    for i, frame in enumerate(frames):
        struct.pack_into("<HH", block, NTH_LENGTH + 8 + 4 * i, offset,
                         len(frame))
        block[offset:offset + len(frame)] = frame
        offset += len(frame)

    if block_length % USB_PACKET_SIZE == 0:
        block.append(0)
    return bytes(block)
