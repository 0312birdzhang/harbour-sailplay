"""TLV8 codec for the HomeKit/AirPlay pairing messages.

PairingSetup and PairVerify exchange small type/length/value records over the
control channel. Values longer than 255 bytes are split into fragments that
carry the same type; two items of the same type in a row are separated by a
``0xff`` record.

Types, fragment size and the separator byte follow xcertplay's
``airplay/Tlv8Codec.kt`` and the ``com.shilapi.xcertplay.airplay.PairSetup``
companion object.
"""

SEPARATOR_TYPE = 0xff
MAX_FRAGMENT_BYTES = 255

TYPE_METHOD = 0x00
TYPE_IDENTIFIER = 0x01
TYPE_SALT = 0x02
TYPE_PUBLIC_KEY = 0x03
TYPE_PROOF = 0x04
TYPE_ENCRYPTED_DATA = 0x05
TYPE_STATE = 0x06
TYPE_ERROR = 0x07
TYPE_SIGNATURE = 0x0a

ERROR_AUTHENTICATION = 2


class Item(object):
    """One TLV8 record: a type byte and an arbitrary-length value."""

    __slots__ = ("type", "value")

    def __init__(self, type_, value):
        self.type = type_
        self.value = bytes(value)

    def __repr__(self):
        return "Item(0x{:02x}, {} bytes)".format(self.type, len(self.value))

    def __eq__(self, other):
        return (isinstance(other, Item)
                and self.type == other.type
                and self.value == other.value)

    def __ne__(self, other):
        return not self.__eq__(other)


def encode(items):
    """Encode items as one contiguous byte buffer.

    Each value is emitted as one or more ``[type][length][value]`` fragments;
    consecutive items sharing a type get a ``[0xff][0x00]`` separator between
    them so the decoder can tell where one value ends and the next begins.
    """
    out = bytearray()
    previous_type = None

    for item in items:
        if previous_type is not None and previous_type == item.type:
            out.append(SEPARATOR_TYPE)
            out.append(0)

        value = item.value
        offset = 0
        while True:
            length = min(MAX_FRAGMENT_BYTES, len(value) - offset)
            out.append(item.type)
            out.append(length)
            out.extend(value[offset:offset + length])
            offset += length
            if offset >= len(value):
                break

        previous_type = item.type

    return bytes(out)


def decode(buffer):
    """Decode a TLV8 buffer into a ``{type: value}`` mapping.

    Fragments sharing a type are concatenated when the previous fragment was a
    full 255-byte one; anything else replaces the earlier value of that type.
    A trailing fragment that runs past the end of the buffer is dropped, so a
    partial read never raises.
    """
    buffer = bytes(buffer)
    total = len(buffer)
    out = {}
    position = 0
    last_type = None
    last_length = 0

    while position + 2 <= total:
        type_ = buffer[position]
        length = buffer[position + 1]
        position += 2
        if position + length > total:
            break

        value = buffer[position:position + length]
        position += length

        if type_ == last_type and last_length == MAX_FRAGMENT_BYTES:
            previous = out.get(type_)
            out[type_] = previous + value if previous is not None else value
        else:
            out[type_] = value

        last_type = type_
        last_length = length

    return out
