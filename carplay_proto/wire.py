"""iAP2 CSM framing: `0x4040 | u16be length | u16be messageId | body`."""

import struct

from . import types


START = 0x4040
HEADER_BYTES = 6
PARAM_HEADER_BYTES = 4
MAX_FRAME_BYTES = 0xffff
MAX_BODY_BYTES = MAX_FRAME_BYTES - HEADER_BYTES
MAX_PARAM_BYTES = 0xffff
MAX_PARAM_PAYLOAD_BYTES = MAX_PARAM_BYTES - PARAM_HEADER_BYTES
MAX_LINK_CHUNK_BYTES = 65525


class ProtocolError(ValueError):
    pass


class Parameter(object):
    __slots__ = ("id", "_payload")

    def __init__(self, id, payload):
        if not 0 <= id <= 0xffff:
            raise ProtocolError("parameter id out of range: {}".format(id))
        if len(payload) > MAX_PARAM_PAYLOAD_BYTES:
            raise ProtocolError(
                "parameter payload exceeds {} bytes".format(MAX_PARAM_PAYLOAD_BYTES))
        self.id = id
        self._payload = bytes(payload)

    @property
    def payload(self):
        return self._payload

    def __eq__(self, other):
        return (isinstance(other, Parameter)
                and self.id == other.id
                and self._payload == other._payload)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.id, self._payload))

    def __repr__(self):
        return "Parameter(0x{:04x}, {} bytes)".format(self.id, len(self._payload))


class Frame(object):
    __slots__ = ("message_id", "_body")

    def __init__(self, message_id, body):
        if not 0 <= message_id <= 0xffff:
            raise ProtocolError("message id out of range: {}".format(message_id))
        if len(body) > MAX_BODY_BYTES:
            raise ProtocolError("body exceeds {} bytes".format(MAX_BODY_BYTES))
        self.message_id = message_id
        self._body = bytes(body)

    @property
    def body(self):
        return self._body

    def parameters(self):
        return parse_params(self._body)

    def encoded(self):
        return encode_frame(self.message_id, self._body)

    def __eq__(self, other):
        return (isinstance(other, Frame)
                and self.message_id == other.message_id
                and self._body == other._body)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "Frame(0x{:04x}, {} bytes)".format(self.message_id, len(self._body))


def encode_frame(message_id, body):
    frame = bytearray(HEADER_BYTES + len(body))
    struct.pack_into(">HHH", frame, 0, START, len(frame), message_id)
    frame[HEADER_BYTES:] = body
    return bytes(frame)


def encode_param(parameter_id, payload):
    param = bytearray(PARAM_HEADER_BYTES + len(payload))
    struct.pack_into(">HH", param, 0, len(param), parameter_id)
    param[PARAM_HEADER_BYTES:] = payload
    return bytes(param)


def parse_params(data):
    """Parse a complete body into an ordered parameter list."""
    params = []
    offset = 0
    size = len(data)
    while offset < size:
        if size - offset < PARAM_HEADER_BYTES:
            raise ProtocolError("truncated parameter header at {}".format(offset))
        length = struct.unpack_from(">H", data, offset)[0]
        if length < PARAM_HEADER_BYTES:
            raise ProtocolError("invalid parameter length {}".format(length))
        if length > size - offset:
            raise ProtocolError("parameter length {} exceeds remaining {}".format(
                length, size - offset))
        pid = struct.unpack_from(">H", data, offset + 2)[0]
        params.append(Parameter(
            pid, data[offset + PARAM_HEADER_BYTES:offset + length]))
        offset += length
    return params


def encode_params(params):
    out = bytearray()
    for param in params:
        encoded = encode_param(param.id, param.payload)
        if len(out) + len(encoded) > MAX_BODY_BYTES:
            raise ProtocolError("encoded parameters exceed the {}-byte body limit".format(
                MAX_BODY_BYTES))
        out += encoded
    return bytes(out)


class Framer(object):
    """Streaming CSM assembler.

    Tolerates arbitrary transport chunking, concatenated frames, and leading
    garbage bytes (discarded while hunting for the start marker).
    """

    def __init__(self, max_buffer=MAX_FRAME_BYTES):
        self._buf = bytearray()
        self._max = max_buffer

    def offer(self, chunk):
        frames = []
        i = 0
        size = len(chunk)
        while i < size:
            self._drain(frames)
            room = self._max - len(self._buf)
            if room <= 0:
                raise ProtocolError("CSM receive buffer could not make progress")
            count = min(size - i, room)
            self._buf += chunk[i:i + count]
            i += count
        self._drain(frames)
        return frames

    def pending(self):
        return len(self._buf)

    def reset(self):
        del self._buf[:]

    def _drain(self, frames):
        while True:
            while (len(self._buf) >= 2
                   and not (self._buf[0] == 0x40 and self._buf[1] == 0x40)):
                del self._buf[:1]
            if len(self._buf) < HEADER_BYTES:
                return
            length = (self._buf[2] << 8) | self._buf[3]
            if length < HEADER_BYTES:
                del self._buf[:1]
                continue
            if len(self._buf) < length:
                return
            message_id = (self._buf[4] << 8) | self._buf[5]
            body = bytes(self._buf[HEADER_BYTES:length])
            del self._buf[:length]
            frames.append(Frame(message_id, body))
