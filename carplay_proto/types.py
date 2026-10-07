"""CSM scalar codecs. All multi-byte integers are big-endian."""

import struct

VOID = "VOID"
BOOL = "BOOL"
U8 = "U8"
I8 = "I8"
U16 = "U16"
I16 = "I16"
U32 = "U32"
I32 = "I32"
U64 = "U64"
U16_LIST = "U16_LIST"
BYTES = "BYTES"
STRING = "STRING"
STRING_LIST = "STRING_LIST"
GROUP = "GROUP"
OPAQUE = "OPAQUE"

SIGNED = (I8, I16, I32)
UNSIGNED = (U8, U16, U32, U64)
SCALARS = (VOID, BOOL) + UNSIGNED + SIGNED


class CodecError(ValueError):
    pass


def _check_range(value, lo, hi, what):
    if not isinstance(value, int) or isinstance(value, bool):
        raise CodecError("{} expects an int, got {!r}".format(what, value))
    if not lo <= value <= hi:
        raise CodecError("{} value {} out of range {}..{}".format(what, value, lo, hi))


def encode(value, type_):
    """Encode a Python value into its CSM wire payload."""
    if type_ == VOID:
        if value is not None:
            raise CodecError("VOID takes no value")
        return b""

    if type_ == BOOL:
        return bytes([1 if value else 0])

    if type_ == U8:
        _check_range(value, 0, 0xff, "u8")
        return bytes([value])

    if type_ == I8:
        _check_range(value, -0x80, 0x7f, "i8")
        return struct.pack(">b", value)

    if type_ == U16:
        _check_range(value, 0, 0xffff, "u16")
        return struct.pack(">H", value)

    if type_ == I16:
        _check_range(value, -0x8000, 0x7fff, "i16")
        return struct.pack(">h", value)

    if type_ == U32:
        _check_range(value, 0, 0xffffffff, "u32")
        return struct.pack(">I", value)

    if type_ == I32:
        _check_range(value, -0x80000000, 0x7fffffff, "i32")
        return struct.pack(">i", value)

    if type_ == U64:
        _check_range(value, 0, 0xffffffffffffffff, "u64")
        return struct.pack(">Q", value)

    if type_ == U16_LIST:
        out = bytearray()
        for item in value:
            _check_range(item, 0, 0xffff, "u16[]")
            out += struct.pack(">H", item)
        return bytes(out)

    if type_ == BYTES:
        return bytes(value)

    if type_ == OPAQUE:
        return bytes(value)

    if type_ == GROUP:
        return bytes(value)

    if type_ == STRING:
        if not isinstance(value, str):
            raise CodecError("STRING expects a str")
        if "\u0000" in value:
            raise CodecError("STRING must not contain U+0000")
        return value.encode("utf-8") + b"\0"

    if type_ == STRING_LIST:
        out = bytearray()
        for item in value:
            if not isinstance(item, str):
                raise CodecError("STRING_LIST expects strs")
            if "\u0000" in item:
                raise CodecError("STRING_LIST items must not contain U+0000")
            out += item.encode("utf-8") + b"\0"
        return bytes(out)

    raise CodecError("unknown type {!r}".format(type_))


def decode(payload, type_):
    """Decode a CSM wire payload into a Python value."""
    data = bytes(payload)

    if type_ == VOID:
        if data:
            raise CodecError("VOID payload must be empty, got {} bytes".format(len(data)))
        return None

    if type_ == BOOL:
        if len(data) != 1:
            raise CodecError("BOOL payload must be 1 byte, got {}".format(len(data)))
        return data[0] != 0

    if type_ == U8:
        if len(data) != 1:
            raise CodecError("u8 payload must be 1 byte, got {}".format(len(data)))
        return data[0]

    if type_ == I8:
        if len(data) != 1:
            raise CodecError("i8 payload must be 1 byte, got {}".format(len(data)))
        return struct.unpack(">b", data)[0]

    if type_ == U16:
        if len(data) != 2:
            raise CodecError("u16 payload must be 2 bytes, got {}".format(len(data)))
        return struct.unpack(">H", data)[0]

    if type_ == I16:
        if len(data) != 2:
            raise CodecError("i16 payload must be 2 bytes, got {}".format(len(data)))
        return struct.unpack(">h", data)[0]

    if type_ == U32:
        if len(data) != 4:
            raise CodecError("u32 payload must be 4 bytes, got {}".format(len(data)))
        return struct.unpack(">I", data)[0]

    if type_ == I32:
        if len(data) != 4:
            raise CodecError("i32 payload must be 4 bytes, got {}".format(len(data)))
        return struct.unpack(">i", data)[0]

    if type_ == U64:
        if len(data) != 8:
            raise CodecError("u64 payload must be 8 bytes, got {}".format(len(data)))
        return struct.unpack(">Q", data)[0]

    if type_ == U16_LIST:
        if len(data) % 2:
            raise CodecError("u16[] payload has odd length {}".format(len(data)))
        return list(struct.unpack(">" + "H" * (len(data) // 2), data))

    if type_ in (BYTES, OPAQUE, GROUP):
        return data

    if type_ == STRING:
        if not data or data[-1] != 0:
            raise CodecError("STRING payload is not NUL terminated")
        return data[:-1].decode("utf-8")

    if type_ == STRING_LIST:
        if not data or data[-1] != 0:
            raise CodecError("STRING_LIST payload is not NUL terminated")
        return [part.decode("utf-8") for part in data.split(b"\0")[:-1]]

    raise CodecError("unknown type {!r}".format(type_))


def size(type_):
    """Wire size in bytes, or None for variable-length types."""
    return {
        VOID: 0,
        BOOL: 1,
        U8: 1,
        I8: 1,
        U16: 2,
        I16: 2,
        U32: 4,
        I32: 4,
        U64: 8,
    }.get(type_)
