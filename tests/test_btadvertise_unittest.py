import importlib.util
import os
import struct
import unittest
import uuid

path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'wireless-phone-advertise.py')
spec = importlib.util.spec_from_file_location('btadvertise', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeSocket:
    def __init__(self, events):
        self.events = list(events)
        self.written = []

    def sendall(self, data):
        self.written.append(data)

    def recv(self, count):
        return self.events.pop(0)


def event(kind, index, opcode, status):
    return struct.pack('<HHHHB', kind, index, 3, opcode, status)


class AdvertisementTests(unittest.TestCase):
    def test_command_uses_selected_adapter_and_ignores_other_controller(self):
        sock = FakeSocket([event(1, 0, 0x10, 0), event(1, 1, 0x10, 0)])
        module.command(sock, 0x10, b'uuid', adapter_index=1)
        self.assertEqual(sock.written, [struct.pack('<HHH', 0x10, 1, 4) + b'uuid'])

    def test_phone_uuid_little_endian_and_complete(self):
        value = uuid.UUID(module.PHONE_EIR).bytes[::-1]
        self.assertEqual(value.hex(), '1a29eaab0173bc881c454de166248d2d')
        sock = FakeSocket([event(1, 1, 0x10, 0), event(1, 0, 0x11, 0),
                           event(2, 0, 0x10, 0), event(1, 0, 0x10, 0)])
        module.command(sock, 0x10, value + b'\x00')
        self.assertEqual(sock.written, [struct.pack('<HHH', 0x10, 0, 17) + value + b'\x00'])

    def test_rejected_command_does_not_claim_success(self):
        sock = FakeSocket([event(2, 0, 0x10, 0x0c)])
        with self.assertRaises(OSError):
            module.command(sock, 0x10, b'')


if __name__ == '__main__':
    unittest.main()
