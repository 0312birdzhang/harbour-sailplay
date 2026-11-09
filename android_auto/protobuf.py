"""The protobuf wire types used by DiAuto's proto2 projection messages.

Keep the device runtime independent of generated-code/protobuf version pairs.
Field numbers and message shapes follow DiAuto's app/src/main/proto schemas.
"""
import struct


MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_FIELDS = 4096


def varint(value):
    if not isinstance(value, int) or not -(1 << 63) <= value < (1 << 64):
        raise ValueError('protobuf integer outside 64-bit range')
    value &= (1 << 64) - 1
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def read_varint(data, offset):
    value = 0
    for index in range(10):
        if offset >= len(data):
            raise ValueError('truncated protobuf varint')
        byte = data[offset]
        offset += 1
        if index == 9 and byte > 1:
            raise ValueError('protobuf varint exceeds 64 bits')
        value |= (byte & 127) << (7 * index)
        if byte < 128:
            return value, offset
    raise ValueError('unterminated protobuf varint')


def field(number, value):
    if not 1 <= number < (1 << 29):
        raise ValueError('invalid protobuf field number')
    if isinstance(value, str):
        value = value.encode('utf-8')
    if isinstance(value, bytes):
        if len(value) > MAX_MESSAGE_BYTES:
            raise ValueError('protobuf byte field exceeds limit')
        return varint(number << 3 | 2) + varint(len(value)) + value
    return varint(number << 3) + varint(value)


class Message:
    def __init__(self, data=b''):
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError('protobuf message exceeds limit')
        self.fields = {}
        offset = count = 0
        while offset < len(data):
            tag, offset = read_varint(data, offset)
            number, kind = tag >> 3, tag & 7
            if not 1 <= number < (1 << 29):
                raise ValueError('invalid protobuf field number')
            count += 1
            if count > MAX_FIELDS:
                raise ValueError('protobuf field count exceeds limit')
            if kind == 0:
                value, offset = read_varint(data, offset)
            elif kind == 2:
                size, offset = read_varint(data, offset)
                end = offset + size
                if end > len(data):
                    raise ValueError('truncated protobuf byte field')
                value, offset = data[offset:end], end
            elif kind in (1, 5):
                size = 8 if kind == 1 else 4
                if offset + size > len(data):
                    raise ValueError('truncated protobuf fixed field')
                value = struct.unpack_from('<Q' if kind == 1 else '<I', data, offset)[0]
                offset += size
            else:
                raise ValueError('unsupported protobuf wire type')
            self.fields.setdefault(number, []).append((kind, value))

    def integer(self, number, default=None, signed=False):
        values = self.fields.get(number)
        if not values:
            return default
        kind, value = values[-1]
        if kind != 0:
            raise ValueError('protobuf integer has wrong wire type')
        if signed:
            value &= 0xffffffff
            if value & 0x80000000:
                value -= 1 << 32
        return value

    def integers(self, number):
        result = []
        for kind, value in self.fields.get(number, []):
            if kind == 0:
                result.append(value)
            elif kind == 2:
                offset = 0
                while offset < len(value):
                    item, offset = read_varint(value, offset)
                    result.append(item)
            else:
                raise ValueError('protobuf integer list has wrong wire type')
            if len(result) > MAX_FIELDS:
                raise ValueError('protobuf integer list exceeds limit')
        return result

    def blobs(self, number):
        result = []
        for kind, value in self.fields.get(number, []):
            if kind != 2:
                raise ValueError('protobuf bytes have wrong wire type')
            result.append(value)
        return result

    def blob(self, number, default=None):
        values = self.blobs(number)
        return values[-1] if values else default

    def text(self, number, default=''):
        value = self.blob(number)
        return value.decode('utf-8') if value is not None else default

    def messages(self, number):
        return [Message(value) for value in self.blobs(number)]
