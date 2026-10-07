"""USBMUX v2 framing: 16-byte little-endian header plus a minimal TCP subset.

Header layout: ``u32le protocol | u32le length | u32le word8 | u32le word12``
where ``word8`` is the 0xfeedface magic for data frames and the mux version
for the proto-0 handshake message, and ``word12`` carries ``u16le seq`` and
``u16le ack``.
"""

import struct


HEADER_BYTES = 16
MAGIC = 0xfeedface
MAX_FRAME_BYTES = 65536
VERSION_MESSAGE_BYTES = 20
USBMUX_VERSION = 2
SETUP_VALUE = 0x07

PROTOCOL_VERSION = 0
PROTOCOL_SETUP = 2
PROTOCOL_TCP = 6

TCP_HEADER_BYTES = 20
TCP_WINDOW_FIELD = 512
TCP_DATA_OFFSET = TCP_HEADER_BYTES // 4
TCP_SYN = 0x02
TCP_RST = 0x04
TCP_ACK = 0x10
TCP_FIN = 0x01
FIRST_SOURCE_PORT = 1
LOCKDOWN_PORT = 62078
MAX_SEND_PAYLOAD_BYTES = 16 * 1024


class TransportError(ValueError):
    pass


def build_version_handshake():
    """The 20-byte proto-0 version message.

    This is a degenerate frame: only the first 12 bytes carry meaning
    (``protocol | length | version``) and the rest is zero padding.
    """
    out = bytearray(VERSION_MESSAGE_BYTES)
    struct.pack_into("<III", out, 0, PROTOCOL_VERSION, VERSION_MESSAGE_BYTES,
                     USBMUX_VERSION)
    return bytes(out)


def build_setup():
    """The proto-2 setup frame, one byte of payload."""
    return build_frame(PROTOCOL_SETUP, bytes([SETUP_VALUE]))


def build_frame(protocol, payload, seq=0, ack=0):
    if len(payload) > MAX_FRAME_BYTES - HEADER_BYTES:
        raise TransportError("payload exceeds the usbmux frame limit")
    out = bytearray(HEADER_BYTES + len(payload))
    struct.pack_into("<II", out, 0, protocol, len(out))
    struct.pack_into("<II", out, 8, MAGIC, ((ack & 0xffff) << 16) | (seq & 0xffff))
    out[HEADER_BYTES:] = payload
    return bytes(out)


def build_tcp_header(source_port, destination_port, sequence, acknowledgement,
                     flags, payload_length):
    out = bytearray(TCP_HEADER_BYTES + payload_length)
    struct.pack_into("<HH", out, 0, source_port & 0xffff,
                     destination_port & 0xffff)
    struct.pack_into("<II", out, 4, sequence & 0xffffffff,
                     acknowledgement & 0xffffffff)
    out[12] = TCP_DATA_OFFSET << 4
    out[13] = flags & 0xff
    struct.pack_into("<H", out, 14, TCP_WINDOW_FIELD)
    return out


def build_tcp_frame(source_port, destination_port, sequence, acknowledgement,
                    flags, payload=b"", seq=0, ack=0):
    """One PROTOCOL_TCP usbmux frame wrapping a minimal TCP segment."""
    tcp = bytearray(build_tcp_header(source_port, destination_port, sequence,
                                     acknowledgement, flags, len(payload)))
    tcp[TCP_HEADER_BYTES:] = payload
    return build_frame(PROTOCOL_TCP, bytes(tcp), seq=seq, ack=ack)


def parse(data, offset=0):
    """Return ``(protocol, length, word8, word12, payload, end)``."""
    if len(data) - offset < HEADER_BYTES:
        raise TransportError("usbmux frame header truncated")
    protocol, length, word8, word12 = struct.unpack_from("<IIII", data, offset)
    if length < HEADER_BYTES:
        raise TransportError("invalid usbmux frame length {}".format(length))
    if length > MAX_FRAME_BYTES:
        raise TransportError("usbmux frame length {} exceeds limit".format(length))
    end = offset + length
    if len(data) < end:
        raise TransportError("usbmux frame truncated: have {} want {}".format(
            len(data), length))
    seq = word12 & 0xffff
    ack = (word12 >> 16) & 0xffff
    return protocol, length, word8, seq, ack, data[offset + HEADER_BYTES:end], end


def parse_tcp(data, offset=0):
    """Return ``(source_port, destination_port, sequence, ack, flags,
    payload_offset, end)`` for a PROTOCOL_TCP frame."""
    protocol, length, word8, seq, ack, payload, end = parse(data, offset)
    if protocol != PROTOCOL_TCP:
        raise TransportError("not a tcp frame, protocol {}".format(protocol))
    if word8 != MAGIC:
        raise TransportError("bad magic 0x{0:08x}".format(word8))
    if len(payload) < TCP_HEADER_BYTES:
        raise TransportError("tcp header truncated")
    source_port, destination_port = struct.unpack_from("<HH", payload, 0)
    sequence, acknowledgement = struct.unpack_from("<II", payload, 4)
    flags = payload[13]
    return (source_port, destination_port, sequence, acknowledgement, flags,
            payload, end)


class FrameDecoder(object):
    """Incremental usbmux frame parser over a byte stream."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk):
        frames = []
        self._buf += chunk
        while True:
            if len(self._buf) < HEADER_BYTES:
                break
            protocol, length, word8, word12 = struct.unpack_from("<IIII",
                                                                 self._buf, 0)
            if not HEADER_BYTES <= length <= MAX_FRAME_BYTES:
                raise TransportError("invalid usbmux frame length {}".format(length))
            if len(self._buf) < length:
                break
            payload = bytes(self._buf[HEADER_BYTES:length])
            del self._buf[:length]
            frames.append((protocol, length, word8, word12, payload))
        return frames

    def pending(self):
        return len(self._buf)
