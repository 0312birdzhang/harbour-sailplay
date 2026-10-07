#!/usr/bin/env python3
"""Read-only MGMT Read Extended Controller Information (hci0)."""
import ctypes
import socket
import struct
import uuid

sock = socket.socket(getattr(socket, 'AF_BLUETOOTH', 31), socket.SOCK_RAW, 1)
sock.settimeout(3)
libc = ctypes.CDLL(None, use_errno=True)
libc.bind.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
address = ctypes.create_string_buffer(struct.pack('=HHH', 31, 65535, 3))
if libc.bind(sock.fileno(), address, 6):
    raise OSError(ctypes.get_errno(), 'MGMT bind failed')
try:
    sock.sendall(struct.pack('<HHH', 0x42, 0, 0))
    while True:
        raw = sock.recv(4096)
        if len(raw) < 9:
            continue
        event, index, size, operation, status = struct.unpack('<HHHHB', raw[:9])
        if index != 0 or operation != 0x42 or event not in (1, 2):
            continue
        if status:
            raise OSError('Read Extended Info status %d' % status)
        if event != 1:
            continue
        body = raw[9:6 + size]
        if len(body) < 19:
            raise ValueError('short controller info')
        eir_length = struct.unpack('<H', body[17:19])[0]
        data = body[19:19 + eir_length]
        print('Controller settings:', hex(struct.unpack('<I', body[13:17])[0]))
        offset = 0
        while offset < len(data):
            length = data[offset]
            if length == 0:
                break
            item = data[offset + 1:offset + 1 + length]
            offset += 1 + length
            if len(item) != length:
                raise ValueError('truncated EIR')
            kind, value = item[0], item[1:]
            if kind in (6, 7):
                print('EIR 128-bit UUIDs:', [str(uuid.UUID(bytes=value[i:i + 16][::-1]))
                      for i in range(0, len(value), 16)])
            elif kind in (8, 9):
                print('EIR name:', value.decode('utf-8', 'replace'))
            else:
                print('EIR field:', hex(kind), 'bytes:', len(value))
        break
finally:
    sock.close()

# MGMT extended info is not a read-back of the controller's EIR UUID list.
# Query the controller's read-only HCI Read Extended Inquiry Response command.
sock = socket.socket(getattr(socket, 'AF_BLUETOOTH', 31), socket.SOCK_RAW, 1)
sock.settimeout(3)
address = ctypes.create_string_buffer(struct.pack('=HHH', 31, 0, 0))
if libc.bind(sock.fileno(), address, 6):
    raise OSError(ctypes.get_errno(), 'HCI raw bind failed')
try:
    sock.setsockopt(0, 2, struct.pack('=IIIH', 0x10, 0xc000, 0, 0x0c51))
    sock.sendall(bytes.fromhex('01510c00'))
    while True:
        raw = sock.recv(4096)
        if len(raw) < 7 or raw[0:2] != bytes.fromhex('040e'):
            continue
        if raw[4:6] != bytes.fromhex('510c'):
            continue
        if raw[6]:
            raise OSError('HCI Read EIR status %d' % raw[6])
        data = raw[8:]
        offset = 0
        advertised = []
        while offset < len(data):
            length = data[offset]
            if not length:
                break
            item = data[offset + 1:offset + 1 + length]
            offset += 1 + length
            if len(item) != length:
                raise ValueError('short controller EIR')
            if item[0] in (6, 7):
                value = item[1:]
                advertised.extend(str(uuid.UUID(bytes=value[i:i + 16][::-1]))
                                  for i in range(0, len(value), 16))
        print('Controller actual EIR 128-bit UUIDs:', advertised)
        break
finally:
    sock.close()
