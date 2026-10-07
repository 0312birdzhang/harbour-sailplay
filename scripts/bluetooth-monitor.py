"""Passive HCI monitor: log disconnect/control metadata, never pairing keys/data."""
import ctypes
import logging
import socket
import struct
import threading


class Monitor:
    def __init__(self):
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
            if index != 0:
                continue
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
