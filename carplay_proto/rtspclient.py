"""Bounded plain RTSP transport for initial AirPlay discovery."""
import socket


class RTSPClient:
    def __init__(self, sock):
        self.sock, self.sequence, self.buffer = sock, 0, b''

    def enable_encryption(self, keys):
        from .controlcipher import ControlCipher
        self.sock = EncryptedSocket(self.sock, ControlCipher(keys.read_key, keys.write_key), self.buffer)
        self.buffer = b''

    def request(self, method, path, body=b'', headers=None):
        self.sequence += 1
        fields = {'CSeq': str(self.sequence), 'Content-Length': str(len(body)),
                  'User-Agent': 'Sailplay/0.1'}
        fields.update(headers or {})
        if any('\r' in str(v) or '\n' in str(v) for v in list(fields) + list(fields.values())):
            raise ValueError('invalid RTSP header')
        self.sock.sendall(('{} {} RTSP/1.0\r\n'.format(method, path) + ''.join(
            '{}: {}\r\n'.format(k, v) for k, v in fields.items()) + '\r\n').encode('ascii') + body)
        while b'\r\n\r\n' not in self.buffer:
            if len(self.buffer) > 65536:
                raise ValueError('oversized RTSP header')
            self._receive()
        head, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
        lines = head.decode('ascii').split('\r\n')
        status = int(lines[0].split()[1])
        response = {}
        for line in lines[1:]:
            key, value = line.split(':', 1)
            key = key.lower()
            if key in response:
                raise ValueError('duplicate RTSP header')
            response[key] = value.strip()
        if response.get('cseq') != str(self.sequence):
            raise ValueError('RTSP sequence mismatch')
        size = int(response.get('content-length', '0'))
        if not 0 <= size <= 4 * 1024 * 1024:
            raise ValueError('oversized RTSP body')
        while len(self.buffer) < size:
            self._receive()
        payload, self.buffer = self.buffer[:size], self.buffer[size:]
        return status, response, payload

    def _receive(self):
        data = self.sock.recv(16384)
        if not data:
            raise EOFError('RTSP peer closed')
        self.buffer += data


class EncryptedSocket:
    def __init__(self, sock, cipher, initial=b''):
        self.sock, self.cipher = sock, cipher
        self.encrypted, self.plain = initial, b''

    def sendall(self, data):
        self.sock.sendall(self.cipher.encrypt(data))

    def recv(self, size):
        while not self.plain:
            result = self.cipher.decrypt(self.encrypted)
            self.encrypted = result.rest
            self.plain += result.data
            if self.plain:
                break
            data = self.sock.recv(16384)
            if not data:
                if self.encrypted:
                    raise EOFError('truncated encrypted control frame')
                return b''
            self.encrypted += data
        data, self.plain = self.plain[:size], self.plain[size:]
        return data

    def close(self):
        self.sock.close()


def connect(address, port, interface, timeout=5):
    # A link-local IPv6 destination requires the Wi-Fi interface scope ID.
    sock = socket.socket(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        destination = (address, port, 0, socket.if_nametoindex(interface)) if ':' in address else (address, port)
        sock.connect(destination)
        return RTSPClient(sock)
    except Exception:
        sock.close()
        raise
