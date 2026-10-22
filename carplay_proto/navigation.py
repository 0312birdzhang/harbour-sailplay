"""HSAE iAP2 route guidance primitives recovered from the receiver.

Only fields traced through the receiver bridge are named here. Enum values
are deliberately supplied by the caller until an iPhone trace verifies them.
See NAVIGATION.md for the binary identity and interpretation limits.
"""

import struct

from .wire import Frame, ProtocolError, encode_param


START = 0x5200
ROUTE = 0x5201
MANEUVER = 0x5202
STOP = 0x5203


def _integer(value, width):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError("navigation integer required")
    if not 0 <= value < (1 << (8 * width)):
        raise ProtocolError("navigation integer out of range")
    return value.to_bytes(width, "big")


def _text(value, max_code_units=30):
    """Limit receiver text without splitting a Unicode scalar or UTF-8 byte."""
    if not isinstance(value, str) or "\0" in value:
        raise ProtocolError("navigation text must be a string without NUL")
    # Validate even the suffix that will not be transmitted.
    value.encode("utf-8")
    result = []
    units = 0
    for character in value:
        length = 2 if ord(character) > 0xffff else 1
        if units + length > max_code_units:
            break
        result.append(character)
        units += length
    return "".join(result).encode("utf-8") + b"\0"


def route_update(state, maneuver_state, current_road, destination,
                 remaining_seconds, remaining_display, remaining_units,
                 next_display, next_units):
    """Build the fields consumed by HSAE's handleRouteGuidanceUpdate.

    State and unit enums are raw iAP2 values, not Organic Maps enums.
    Remaining time is seconds, not an absolute ETA or floating-point value.
    """
    fields = [(1, _integer(state, 1)), (2, _integer(maneuver_state, 1)),
              (3, _text(current_road)), (4, _text(destination)),
              (6, _integer(remaining_seconds, 8)),
              (8, _text(remaining_display)), (9, _integer(remaining_units, 1)),
              (11, _text(next_display)), (12, _integer(next_units, 1))]
    return Frame(ROUTE, b"".join(encode_param(key, value) for key, value in fields))


def maneuver_information(maneuver_type, after_road, driving_side):
    """Build the fields forwarded to the meter; enums are raw iAP2 values."""
    fields = [(3, _integer(maneuver_type, 1)), (4, _text(after_road)),
              (7, _integer(driving_side, 1))]
    return Frame(MANEUVER, b"".join(encode_param(key, value) for key, value in fields))


class NavigationSubscription:
    """Per-RFCOMM subscription state; no navigation is sent implicitly.

    Parse before mutating so a malformed request cannot erase a valid one.
    The HSAE stop implementation serializes its component ID in host order;
    accept that byte order only when it matches the active component.
    """

    def __init__(self):
        self.component = None
        self.options = frozenset()

    def offer(self, frame):
        if frame.message_id not in (START, STOP):
            return False
        parameters = {}
        for parameter in frame.parameters():
            if parameter.id in parameters:
                raise ProtocolError("duplicate navigation subscription parameter")
            parameters[parameter.id] = parameter.payload
        component = parameters.get(0)
        if component is None or len(component) != 2:
            raise ProtocolError("navigation subscription needs a 16-bit component ID")
        identifier = struct.unpack(">H", component)[0]
        if frame.message_id == START:
            for key in (1, 2, 3):
                if key in parameters and parameters[key]:
                    raise ProtocolError("navigation subscription option must be empty")
            self.component = identifier
            self.options = frozenset(key for key in parameters if key in (1, 2, 3))
        elif self.component in (identifier, struct.unpack("<H", component)[0]):
            self.component = None
            self.options = frozenset()
        return True
