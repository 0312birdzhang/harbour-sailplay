#!/usr/bin/env python3
"""Temporarily add the CarPlay phone EIR UUID; run probe; remove our UUID."""
import ctypes
import logging
import os
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid

PHONE_EIR = '2d8d2466-e14d-451c-88bc-7301abea291a'


def command(sock, opcode, payload):
    sock.sendall(struct.pack('<HHH', opcode, 0, len(payload)) + payload)
    end = time.monotonic() + 3
    while time.monotonic() < end:
        raw = sock.recv(4096)
        if len(raw) < 9:
            continue
        event, index, length = struct.unpack('<HHH', raw[:6])
        if index != 0 or length < 3 or len(raw) < 6 + length or event not in (1, 2):
            continue
        response, status = struct.unpack('<HB', raw[6:9])
        if response != opcode:
            continue
        if status:
            raise OSError('Bluetooth MGMT status %d for opcode 0x%x' % (status, opcode))
        if event == 1:
            return
    raise TimeoutError('Bluetooth MGMT command did not complete')


def main():
    import dbus
    bus = dbus.SystemBus()
    props = dbus.Interface(bus.get_object('org.bluez', '/org/bluez/hci0'),
                           'org.freedesktop.DBus.Properties')
    existing = [str(v).lower() for v in props.Get('org.bluez.Adapter1', 'UUIDs')]
    probe = os.path.join(os.path.dirname(__file__), 'wireless-probe.py')
    if PHONE_EIR in existing:
        return subprocess.call([sys.executable, probe] + sys.argv[1:])
    # Sailfish Python omits AF_BLUETOOTH even though the Linux kernel supports it.
    bluetooth_family = getattr(socket, 'AF_BLUETOOTH', 31)
    sock = socket.socket(bluetooth_family, socket.SOCK_RAW, 1)
    sock.settimeout(3)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.bind.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    libc.bind.restype = ctypes.c_int
    # sockaddr_hci: family, HCI_DEV_NONE, HCI_CHANNEL_CONTROL.
    address = ctypes.create_string_buffer(struct.pack('=HHH', bluetooth_family, 65535, 3))
    if libc.bind(sock.fileno(), address, 6):
        error = ctypes.get_errno()
        sock.close()
        raise OSError(error, os.strerror(error))
    value = uuid.UUID(PHONE_EIR).bytes[::-1]
    added = False
    monitor = None
    try:
        command(sock, 0x0010, value + b'\x00')
        added = True
        logging.info('temporary CarPlay phone EIR added on hci0')
        try:
            import importlib.util
            path = os.path.join(os.path.dirname(__file__), 'bluetooth-monitor.py')
            spec = importlib.util.spec_from_file_location('sailplay_monitor', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            monitor = module.Monitor()
        except (OSError, ImportError, AttributeError):
            logging.exception('passive HCI monitoring unavailable')
        return subprocess.call([sys.executable, probe] + sys.argv[1:])
    finally:
        try:
            if monitor:
                monitor.close()
            if added:
                command(sock, 0x0011, value)
                logging.info('temporary CarPlay phone EIR removed')
        finally:
            sock.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    # SIGTERM must run the UUID cleanup instead of terminating immediately.
    def terminate(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, terminate)
    sys.exit(main())
