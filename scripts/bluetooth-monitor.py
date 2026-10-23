"""Passive HCI monitor: log disconnect/control metadata, never pairing keys/data."""
import ctypes
import logging
import socket
import struct
import threading
import uuid


def eir_summary(data):
    """Only public service markers; never record names or manufacturer data."""
    services = []
    offset = 0
    while offset < len(data) and data[offset]:
        size = data[offset]
        if size < 1 or offset + size + 1 > len(data):
            return {'malformed': True, 'uuids128': services}
        kind = data[offset + 1]
        value = data[offset + 2:offset + size + 1]
        if kind in (6, 7):
            if len(value) % 16:
                return {'malformed': True, 'uuids128': services}
            services.extend(str(uuid.UUID(bytes=value[i:i+16][::-1]))
                            for i in range(0, len(value), 16))
        offset += size + 1
    return {'malformed': False, 'uuids128': services}


def public_hci_metadata(opcode, data):
    if opcode == 2 and len(data) >= 4:
        command, length = struct.unpack('<HB', data[:3])
        if command == 0x0c52 and length == 241 and len(data) == 244:
            logging.info('HCI EIR write fec=%d summary=%s', data[3], eir_summary(data[4:]))
    if opcode != 3 or len(data) < 2 or len(data) != data[1] + 2:
        return
    event, size = data[:2]
    if event == 0x0e and size >= 4:
        command = struct.unpack('<H', data[3:5])[0]
        if command == 0x0c52:
            logging.info('HCI EIR write complete status=0x%02x', data[5])
    elif event == 0x36 and size == 7:
        logging.info('HCI simple pairing complete status=0x%02x', data[2])
    elif event == 0x06 and size == 3:
        logging.info('HCI authentication complete status=0x%02x handle=%d',
                     data[2], struct.unpack('<H', data[3:5])[0])


class Monitor:
    def __init__(self, adapter_index=0):
        self.adapter_index = adapter_index
        self.stop = threading.Event()
        self.pending = {}
        self.rfcomm = set()
        self.sock = socket.socket(getattr(socket, 'AF_BLUETOOTH', 31), socket.SOCK_RAW, 1)
        self.sock.settimeout(0.2)
        libc = ctypes.CDLL(None, use_errno=True)
        libc.bind.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
        address = ctypes.create_string_buffer(struct.pack('=HHH', 31, 65535, 2))
        if libc.bind(self.sock.fileno(), address, 6):
            error = ctypes.get_errno()
            self.sock.close()
            raise OSError(error, 'cannot bind HCI monitor')
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                raw = self.sock.recv(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            if len(raw) < 6:
                continue
            opcode, index, size = struct.unpack('<HHH', raw[:6])
            data = raw[6:6 + size]
            if index != self.adapter_index:
                continue
            public_hci_metadata(opcode, data)
            if opcode == 3 and len(data) >= 6 and data[0] == 5:
                status, handle, reason = struct.unpack('<BHB', data[2:6])
                logging.info('HCI disconnect handle=%d status=%d reason=0x%02x', handle, status, reason)
            if opcode not in (4, 5) or len(data) < 8:
                continue
            handle_flags, acl_size, length, cid = struct.unpack('<HHHH', data[:8])
            handle = handle_flags & 4095
            # Continuations are deliberately ignored: this metadata monitor does not
            # deliver any data or claim to reassemble application streams.
            if (handle_flags >> 12) & 3 not in (0, 2) or len(data) < 8 + length:
                continue
            direction = 'tx' if opcode == 4 else 'rx'
            payload = data[8:8 + length]
            if cid == 1:
                offset = 0
                while len(payload) - offset >= 4:
                    code, ident, count = struct.unpack('<BBH', payload[offset:offset + 4])
                    body = payload[offset + 4:offset + 4 + count]
                    offset += 4 + count
                    if len(body) != count:
                        break
                    if code == 2 and count == 4:
                        psm, scid = struct.unpack('<HH', body)
                        self.pending[(handle, direction, ident)] = (psm, scid)
                        logging.info('L2CAP %s connect psm=0x%04x cid=%d', direction, psm, scid)
                    elif code == 3 and count == 8:
                        dcid, scid, result, status = struct.unpack('<HHHH', body)
                        previous = self.pending.get((handle, 'rx' if direction == 'tx' else 'tx', ident))
                        if previous and previous[0] == 3 and result == 0:
                            self.rfcomm.update(((handle, dcid), (handle, scid)))
                        logging.info('L2CAP %s response result=%d status=%d', direction, result, status)
                    elif code in (6, 7) and count == 4:
                        dcid, scid = struct.unpack('<HH', body)
                        logging.info('L2CAP %s disconnect code=%d cids=%d/%d', direction, code, dcid, scid)
            elif (handle, cid) in self.rfcomm and len(payload) >= 3:
                control = payload[1] & 0xef
                name = {0x2f: 'SABM', 0x63: 'UA', 0x0f: 'DM', 0x43: 'DISC', 0xef: 'UIH'}.get(control, 'other')
                logging.info('RFCOMM %s %s dlci=%d bytes=%d', direction, name, payload[0] >> 2, len(payload))

    def close(self):
        self.stop.set()
        self.thread.join(1)
        self.sock.close()
