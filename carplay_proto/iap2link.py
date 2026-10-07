"""iAP2 link framing, independent of RFCOMM and CSM (Python 3.6+)."""
import struct
from collections import namedtuple

DETECT = bytes.fromhex('ff550200ee10')
SYN, ACK, EAK, RST = 0x80, 0x40, 0x20, 0x10
Packet = namedtuple('Packet', 'control sequence acknowledgement session payload')


def encode(packet):
    payload = packet.payload
    size = 9 if payload is None else 10 + len(payload)
    if size > 65535:
        raise ValueError('iAP2 packet too large')
    header = struct.pack('>2sHBBBB', b'\xff\x5a', size, packet.control,
                         packet.sequence, packet.acknowledgement, packet.session)
    result = header + bytes([(-sum(header)) & 255])
    if payload is not None:
        result += payload + bytes([(-sum(payload)) & 255])
    return result


def synchronization(session=10, max_length=4096):
    """Version 1, one outstanding packet, one control session."""
    if not 10 < max_length <= 65535:
        raise ValueError('invalid maximum packet length')
    return struct.pack('>BBHHHBBBBB', 1, 1, max_length, 1000, 100, 5, 1,
                       session, 0, 1)


def parse_synchronization(payload):
    if len(payload) < 13 or (len(payload) - 10) % 3 or payload[0] != 1:
        raise ValueError('invalid iAP2 synchronization')
    limits = struct.unpack('>BBHHHBB', payload[:10])
    if limits[1] == 0 or limits[2] <= 10:
        raise ValueError('unusable peer packet limits')
    sessions = [tuple(payload[i:i + 3]) for i in range(10, len(payload), 3)]
    return limits, sessions


class Decoder:
    """Incremental bounded parser. Returns DETECT or validated Packet objects.

    Corrupt input is resynchronized; counters let a probe report corruption.
    No byte from a failed payload checksum is delivered to a control session.
    """
    def __init__(self):
        self.buffer = bytearray()
        self.errors = 0

    def feed(self, chunk):
        result = []
        # Process chunks incrementally even if a caller supplies a huge buffer.
        for offset in range(0, len(chunk), 4096):
            self.buffer.extend(chunk[offset:offset + 4096])
            while self.buffer:
                if self.buffer.startswith(DETECT):
                    del self.buffer[:len(DETECT)]
                    result.append(DETECT)
                    continue
                if DETECT.startswith(self.buffer):
                    break
                if self.buffer[0] != 255:
                    del self.buffer[0]
                    continue
                if len(self.buffer) < 2:
                    break
                if self.buffer[1] != 0x5a:
                    del self.buffer[0]
                    continue
                if len(self.buffer) < 9:
                    break
                size = struct.unpack('>H', self.buffer[2:4])[0]
                if size < 9 or sum(self.buffer[:9]) & 255:
                    self.errors += 1
                    del self.buffer[0]
                    continue
                if len(self.buffer) < size:
                    break
                raw = bytes(self.buffer[:size])
                del self.buffer[:size]
                if size > 9 and sum(raw[9:]) & 255:
                    self.errors += 1
                    continue
                result.append(Packet(*raw[4:8], None if size == 9 else raw[9:-1]))
        return result
