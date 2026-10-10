#!/usr/bin/python3
"""Extract embedded MP3/FLAC artwork when a player supplies no MPRIS art URL."""
import os
import sys
from pathlib import Path

LIMIT = 8 * 1024 * 1024


def syncsafe(value):
    if len(value) != 4 or any(byte & 128 for byte in value):
        raise ValueError('invalid ID3 size')
    return sum(byte << shift for byte, shift in zip(value, (21, 14, 7, 0)))


def picture(payload, legacy=False):
    if len(payload) < 5:
        return None
    encoding = payload[0]
    if legacy:
        rest = payload[5:]
    else:
        end = payload.find(b'\0', 1)
        if end < 0 or payload[1:end] == b'-->':
            return None
        rest = payload[end + 2:]
    if encoding in (1, 2):
        end = next((i for i in range(0, len(rest)-1, 2) if rest[i:i+2] == b'\0\0'), -1)
        return rest[end+2:] if end >= 0 else None
    end = rest.find(b'\0')
    return rest[end+1:] if end >= 0 else None


def extract(source):
    with open(source, 'rb') as stream:
        head = stream.read(10)
        if head[:3] == b'ID3' and head[3] in (2, 3, 4):
            version = head[3]
            size = syncsafe(head[6:10])
            if size > LIMIT:
                return None
            data = stream.read(size)
            if head[5] & 128:
                data = data.replace(b'\xff\0', b'\xff')
            offset = 0
            if head[5] & 64 and version in (3, 4):
                offset = (int.from_bytes(data[:4], 'big') + 4 if version == 3 else syncsafe(data[:4]))
            header = 6 if version == 2 else 10
            while offset + header <= len(data):
                frame = data[offset:offset+header]
                name = frame[:3 if version == 2 else 4]
                count = (int.from_bytes(frame[3:6], 'big') if version == 2 else
                         syncsafe(frame[4:8]) if version == 4 else int.from_bytes(frame[4:8], 'big'))
                if not count or offset + header + count > len(data):
                    break
                payload = data[offset+header:offset+header+count]
                if name in (b'APIC', b'PIC'):
                    # Compressed/encrypted frames cannot be treated as images.
                    if version == 2 or not (frame[9] & (0x0c if version == 4 else 0xc0)):
                        if version == 4 and frame[9] & 2:
                            payload = payload.replace(b'\xff\0', b'\xff')
                        return picture(payload, version == 2)
                offset += header + count
        elif head[:4] == b'fLaC':
            stream.seek(4)
            while True:
                block = stream.read(4)
                if len(block) != 4:
                    break
                size = int.from_bytes(block[1:], 'big')
                if block[0] & 127 == 6:
                    if size > LIMIT:
                        return None
                    data = stream.read(size)
                    offset = 4
                    for _ in range(2):
                        count = int.from_bytes(data[offset:offset+4], 'big')
                        offset += 4 + count
                    offset += 16
                    count = int.from_bytes(data[offset:offset+4], 'big')
                    image = data[offset+4:offset+4+count]
                    return image if len(image) == count else None
                stream.seek(size, 1)
                if block[0] & 128:
                    break
    return None


def main():
    image = extract(sys.argv[1])
    if not image or len(image) > LIMIT:
        return 1
    if not (image.startswith(b'\xff\xd8\xff') or image.startswith(b'\x89PNG\r\n\x1a\n')):
        return 1
    target = Path(sys.argv[2])
    temporary = target.with_suffix('.tmp')
    temporary.write_bytes(image)
    os.replace(temporary, target)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, IndexError):
        sys.exit(1)
