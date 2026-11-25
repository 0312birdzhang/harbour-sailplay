"""Passive HCI monitor: log disconnect/control metadata, never pairing keys/data."""
import ctypes
import logging
import socket
import struct
import threading
import uuid

from carplay_proto.runtime_logging import RepeatGate

# bluetoothd rewrites the inquiry response on every service-record change.
eir_repeats = RepeatGate()


def repeat_note(kind):
    """None when this repeat is not logged, else a suffix counting the dropped ones."""
    skipped = eir_repeats.admit(kind)
    if skipped is None:
        return None
    return ' similarEventsNotLogged={}'.format(skipped) if skipped else ''


def disconnect_reason(reason):
    return {0x05: 'authentication failure', 0x08: 'connection timeout',
            0x13: 'remote user terminated', 0x14: 'remote low resources',
            0x15: 'remote power off', 0x16: 'local host terminated',
            0x22: 'LMP response timeout', 0x3e: 'connection establishment failed'}.get(reason, 'other')


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
            summary = eir_summary(data[4:])
            note = repeat_note(('write', data[3], str(summary)))
            if note is not None:
                logging.info('HCI EIR write fec=%d summary=%s%s', data[3], summary, note)
        elif command == 0x0406 and length == 3 and len(data) == 6:
            handle, reason = struct.unpack('<HB', data[3:])
            logging.info('HCI local Disconnect command handle=%d reason=0x%02x reasonName=%s',
                         handle, reason, disconnect_reason(reason))
    if opcode != 3 or len(data) < 2 or len(data) != data[1] + 2:
        return
    event, size = data[:2]
    if event == 0x0e and size >= 4:
        command = struct.unpack('<H', data[3:5])[0]
        if command == 0x0c52:
            note = repeat_note(('complete', data[5]))
            if note is not None:
                logging.info('HCI EIR write complete status=0x%02x%s', data[5], note)
    elif event == 0x36 and size == 7:
        logging.info('HCI simple pairing complete status=0x%02x', data[2])
    elif event == 0x06 and size == 3:
        logging.info('HCI authentication complete status=0x%02x handle=%d',
                     data[2], struct.unpack('<H', data[3:5])[0])
    elif event == 0x03 and size == 11:
        peer = ':'.join('{:02X}'.format(byte) for byte in data[5:11][::-1])
        logging.info('HCI connection complete status=0x%02x handle=%d peer=%s linkType=%d encrypted=%d',
                     data[2], struct.unpack('<H', data[3:5])[0], peer, data[11], data[12])


class Monitor:
    def __init__(self, adapter_index=0):
        self.adapter_index = adapter_index
        self.stop = threading.Event()
        self.pending = {}
        self.rfcomm = set()
        self.peers = {}
        self.sock = socket.socket(getattr(socket, 'AF_BLUETOOTH', 31), socket.SOCK_RAW, 1)
        self.sock.settimeout(0.2)
        libc = ctypes.CDLL(None, use_errno=True)
        libc.bind.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
        address = ctypes.create_string_buffer(struct.pack('=HHH', 31, 65535, 2))
        if libc.bind(self.sock.fileno(), address, 6):
            error = ctypes.get_errno()
            self.sock.close()
            raise OSError(error, 'cannot bind HCI monitor')
        self.thread = threading.Thread(target=self.run, name='HCI-monitor', daemon=True)
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
            self.process(opcode, data)

    def process(self, opcode, data):
        public_hci_metadata(opcode, data)
        if opcode == 3 and len(data) == 13 and data[:2] == b'\x03\x0b' and data[2] == 0:
            handle = struct.unpack('<H', data[3:5])[0]
            self.peers[handle] = ':'.join('{:02X}'.format(byte) for byte in data[5:11][::-1])
        if opcode == 3 and len(data) == 6 and data[:2] == b'\x05\x04':
            status, handle, reason = struct.unpack('<BHB', data[2:6])
            logging.info('HCI disconnect handle=%d peer=%s status=%d reason=0x%02x reasonName=%s',
                         handle, self.peers.get(handle, 'unknown'), status, reason, disconnect_reason(reason))
            if status == 0:
                self.peers.pop(handle, None)
                self.pending = {key: value for key, value in self.pending.items() if key[0] != handle}
                self.rfcomm = {entry for entry in self.rfcomm if entry[0] != handle}
        if opcode not in (4, 5) or len(data) < 8:
            return
        handle_flags, acl_size, length, cid = struct.unpack('<HHHH', data[:8])
        handle = handle_flags & 4095
        # Continuations are deliberately ignored: this metadata monitor does not
        # deliver any data or claim to reassemble application streams.
        if (handle_flags >> 12) & 3 not in (0, 2) or len(data) < 8 + length:
            return
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
                    logging.info('L2CAP %s connect handle=%d peer=%s psm=0x%04x cid=%d',
                                 direction, handle, self.peers.get(handle, 'unknown'), psm, scid)
                elif code == 3 and count == 8:
                    dcid, scid, result, status = struct.unpack('<HHHH', body)
                    previous = self.pending.pop((handle, 'rx' if direction == 'tx' else 'tx', ident), None)
                    if previous and previous[0] == 3 and result == 0:
                        self.rfcomm.update(((handle, dcid), (handle, scid)))
                    logging.info('L2CAP %s response handle=%d cids=%d/%d result=%d status=%d',
                                 direction, handle, dcid, scid, result, status)
                elif code in (6, 7) and count == 4:
                    dcid, scid = struct.unpack('<HH', body)
                    logging.info('L2CAP %s disconnect handle=%d code=%d cids=%d/%d', direction, handle, code, dcid, scid)
        elif (handle, cid) in self.rfcomm and len(payload) >= 3:
            control = payload[1] & 0xef
            name = {0x2f: 'SABM', 0x63: 'UA', 0x0f: 'DM', 0x43: 'DISC', 0xef: 'UIH'}.get(control, 'other')
            if name != 'UIH':
                logging.info('RFCOMM %s %s handle=%d peer=%s dlci=%d bytes=%d',
                             direction, name, handle, self.peers.get(handle, 'unknown'), payload[0] >> 2, len(payload))

    def close(self):
        self.stop.set()
        self.thread.join(1)
        self.sock.close()
