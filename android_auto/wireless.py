"""Phone-side Bluetooth Wi-Fi Projection Protocol (WPP)."""
import ipaddress
import re
import select
import struct
import threading
import time

from .protobuf import Message, field


AA_UUID = '4de17a00-52cb-11e6-bdf4-0800200c9a66'
MAX_WPP_BYTES = 8192


def wpp_frame(message_type, payload=b''):
    if not 1 <= message_type <= 65535 or len(payload) > MAX_WPP_BYTES:
        raise ValueError('invalid WPP message size or type')
    return struct.pack('>HH', len(payload), message_type) + payload


class WppReader:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        if len(self.buffer) + len(data) > MAX_WPP_BYTES * 2:
            raise ValueError('WPP receive buffer exceeds limit')
        self.buffer.extend(data)

    def next(self):
        if len(self.buffer) < 4:
            return None
        size, message_type = struct.unpack_from('>HH', self.buffer)
        if size > MAX_WPP_BYTES or not message_type:
            raise ValueError('invalid WPP header')
        if len(self.buffer) < size + 4:
            return None
        payload = bytes(self.buffer[4:size + 4])
        del self.buffer[:size + 4]
        return message_type, payload


class Credentials:
    def __init__(self, endpoint, payload):
        info = Message(payload)
        self.address, self.port = endpoint
        self.ssid, self.password = info.text(1), info.text(2)
        self.bssid = info.text(3)
        self.security = info.integer(4, 8)
        self.ap_type = info.integer(5, 0)
        if not 1 <= len(self.ssid.encode('utf-8')) <= 32 or '\x00' in self.ssid:
            raise ValueError('invalid WPP network name')
        if self.security not in (1, 4, 8, 12) or self.ap_type not in (0, 1):
            raise ValueError('unsupported WPP access point security')
        if self.security != 1 and not (8 <= len(self.password.encode('utf-8')) <= 63
                or re.fullmatch(r'[0-9a-fA-F]{64}', self.password)):
            raise ValueError('invalid WPP WPA passphrase')
        if '\x00' in self.password:
            raise ValueError('invalid WPP WPA passphrase')
        if self.bssid and not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', self.bssid):
            raise ValueError('invalid WPP access point address')


class WppClient:
    def __init__(self, sock, stop):
        self.sock, self.stop = sock, stop
        self.sock.settimeout(2)
        self.reader = WppReader()
        self.send_lock = threading.Lock()

    def send(self, message_type, payload=b''):
        with self.send_lock:
            self.sock.sendall(wpp_frame(message_type, payload))

    def receive(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.stop.is_set():
            packet = self.reader.next()
            if packet is not None:
                return packet
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if not select.select([self.sock], [], [], min(.1, remaining))[0]:
                continue
            data = self.sock.recv(4096)
            if not data:
                raise EOFError('head unit closed WPP')
            self.reader.feed(data)
        raise InterruptedError('WPP session stopped')

    def negotiate(self, serial='', timeout=30):
        endpoint = None
        deadline = time.monotonic() + timeout
        for _ in range(128):
            packet = self.receive(max(0, deadline - time.monotonic()))
            if packet is None:
                raise TimeoutError('head unit did not supply WPP credentials')
            message_type, payload = packet
            if message_type == 8:
                self.send(9, payload)
            elif message_type == 4:
                version = Message(payload)
                major, minor = version.integer(1, 1, signed=True), version.integer(2, 1, signed=True)
                status = 0 if major == 1 and minor >= 0 else -1
                self.send(5, field(1, 1) + field(2, min(max(minor, 0), 1))
                          + field(3, serial) + field(4, status))
                if status:
                    raise ValueError('unsupported WPP protocol version')
            elif message_type == 1:
                start = Message(payload)
                address, port = start.text(1), start.integer(2, signed=True)
                ip = ipaddress.ip_address(address)
                if (ip.is_unspecified or ip.is_loopback or ip.is_multicast
                        or port is None or not 1 <= port <= 65535 or start.integer(3, 0, signed=True)):
                    raise ValueError('invalid WPP projection endpoint')
                received_endpoint = (address, port)
                if endpoint is not None and endpoint != received_endpoint:
                    raise ValueError('WPP endpoint changed during handshake')
                endpoint = received_endpoint
                self.send(2)
            elif message_type == 3:
                if endpoint is None:
                    raise ValueError('WPP credentials arrived before projection endpoint')
                credentials = Credentials(endpoint, payload)
                self.send(7, field(3, 0))
                return credentials
            elif message_type != 9:
                raise ValueError('unexpected head-unit WPP message')
        raise ValueError('WPP handshake message count exceeds limit')

    def join_status(self, status, address=None):
        if address is not None:
            self.send(7, field(1, address) + field(3, status))
        self.send(6, field(1, status))
