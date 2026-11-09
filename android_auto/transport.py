"""AAP framing and the phone's TLS-server role inside a TCP connection."""
import collections
import os
import select
import socket
import ssl
import stat
import struct
import tempfile
import time

from .protobuf import MAX_MESSAGE_BYTES, Message


FIRST = 1
LAST = 2
CONTROL = 4
ENCRYPTED = 8
CHUNK_BYTES = 16384
Fragment = collections.namedtuple('Fragment', 'channel flags data total')
Packet = collections.namedtuple('Packet', 'channel type payload')


def frame(channel, flags, data, total=None):
    if not 0 <= channel <= 255 or not 0 <= flags <= 15:
        raise ValueError('invalid AAP channel or flags')
    if not 0 < len(data) <= 65535:
        raise ValueError('invalid AAP fragment length')
    first_fragment = flags & (FIRST | LAST) == FIRST
    if first_fragment != (total is not None):
        raise ValueError('AAP first fragment requires a total length')
    header = struct.pack('>BBH', channel, flags, len(data))
    if first_fragment:
        if not 2 <= total <= MAX_MESSAGE_BYTES:
            raise ValueError('invalid AAP message total')
        header += struct.pack('>I', total)
    return header + data


class FrameReader:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        if len(self.buffer) + len(data) > 256 * 1024:
            raise ValueError('AAP receive buffer exceeds limit')
        self.buffer.extend(data)

    def next(self):
        if len(self.buffer) < 4:
            return None
        channel, flags, size = struct.unpack_from('>BBH', self.buffer)
        if flags & ~15 or not size:
            raise ValueError('invalid AAP fragment header')
        fragmented_first = flags & (FIRST | LAST) == FIRST
        header_size = 8 if fragmented_first else 4
        if len(self.buffer) < header_size:
            return None
        total = struct.unpack_from('>I', self.buffer, 4)[0] if fragmented_first else None
        if total is not None and not 2 <= total <= MAX_MESSAGE_BYTES:
            raise ValueError('invalid AAP message total')
        if len(self.buffer) < header_size + size:
            return None
        data = bytes(self.buffer[header_size:header_size + size])
        del self.buffer[:header_size + size]
        return Fragment(channel, flags, data, total)


class MessageAssembler:
    def __init__(self):
        self.pending = {}
        self.buffered = 0

    def add(self, fragment, plaintext):
        channel, flags = fragment.channel, fragment.flags
        first, last = bool(flags & FIRST), bool(flags & LAST)
        if first:
            if channel in self.pending:
                raise ValueError('AAP message lost its final fragment')
            if last:
                return self.packet(channel, plaintext)
            self.pending[channel] = (fragment.total, flags & (CONTROL | ENCRYPTED), bytearray())
        if channel not in self.pending:
            raise ValueError('AAP fragment has no message start')
        total, mode, data = self.pending[channel]
        if flags & (CONTROL | ENCRYPTED) != mode:
            raise ValueError('AAP fragment mode changed within message')
        if len(data) + len(plaintext) > total or self.buffered + len(plaintext) > MAX_MESSAGE_BYTES:
            raise ValueError('AAP assembled message exceeds declared size')
        data.extend(plaintext)
        self.buffered += len(plaintext)
        if not last:
            return None
        del self.pending[channel]
        self.buffered -= len(data)
        if len(data) != total:
            raise ValueError('AAP assembled message length mismatch')
        return self.packet(channel, bytes(data))

    @staticmethod
    def packet(channel, data):
        if len(data) < 2:
            raise ValueError('AAP message type missing')
        return Packet(channel, struct.unpack_from('>H', data)[0], data[2:])


def _write_identity(certificate, key, directory):
    from .identity import create_identity
    certificate_pem, key_pem = create_identity()
    with tempfile.TemporaryDirectory(prefix='.identity-', dir=directory) as staging:
        descriptor = os.open(staging + '/key', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(key_pem)
        with open(staging + '/certificate', 'wb') as stream:
            stream.write(certificate_pem)
        os.replace(staging + '/key', key)
        os.replace(staging + '/certificate', certificate)


def server_context(certificate=None, key=None, directory='/var/lib/sailplay/android-auto'):
    """Use an installation-local identity, or explicitly supplied credentials."""
    if bool(certificate) != bool(key):
        raise ValueError('both TLS certificate and key are required')
    managed = certificate is None
    if managed:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        certificate, key = directory + '/identity.crt', directory + '/identity.key'
        if not os.path.exists(certificate) or not os.path.exists(key):
            _write_identity(certificate, key, directory)
        if not stat.S_ISREG(os.lstat(key).st_mode) or os.stat(key).st_mode & 0o077:
            raise RuntimeError('Android Auto private key permissions must be 0600')
    context = ssl.SSLContext(getattr(ssl, 'PROTOCOL_TLS_SERVER', ssl.PROTOCOL_TLS))
    if hasattr(ssl, 'TLSVersion'):
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
    else:
        context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | getattr(ssl, 'OP_NO_TLSv1_3', 0)
    try:
        context.load_cert_chain(certificate, key)
    except ssl.SSLError as error:
        if not managed or error.reason != 'KEY_VALUES_MISMATCH':
            raise
        # Recover a generation interrupted between the two file replacements.
        _write_identity(certificate, key, directory)
        context.load_cert_chain(certificate, key)
    return context


class Transport:
    """One I/O thread owns the SSLObject and both memory BIOs."""
    def __init__(self, sock, context, stop=None):
        self.sock, self.context, self.stop = sock, context, stop
        self.reader = FrameReader()
        self.assembler = MessageAssembler()
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.incoming, self.outgoing, server_side=True)
        self.ready = False
        self.partial_since = None
        self.sock.settimeout(2)

    def stopped(self):
        return self.stop is not None and self.stop.is_set()

    def receive_fragment(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.stopped():
            fragment = self.reader.next()
            if fragment is not None:
                self.partial_since = time.monotonic() if self.reader.buffer else None
                return fragment
            if self.partial_since is not None and time.monotonic() - self.partial_since > 5:
                raise TimeoutError('AAP peer left an incomplete fragment')
            remaining = deadline - time.monotonic()
            if remaining < 0:
                return None
            if not select.select([self.sock], [], [], min(remaining, .1))[0]:
                continue
            data = self.sock.recv(65536)
            if not data:
                raise EOFError('AAP peer closed the connection')
            if self.partial_since is None:
                self.partial_since = time.monotonic()
            self.reader.feed(data)
        raise InterruptedError('AAP session stopped')

    def send_plain(self, message_type, payload=b''):
        self.sock.sendall(frame(0, FIRST | LAST, struct.pack('>H', message_type) + payload))

    def plain(self, deadline):
        fragment = self.receive_fragment(max(0, deadline - time.monotonic()))
        if fragment is None:
            raise TimeoutError('AAP handshake timed out')
        if fragment.channel != 0 or fragment.flags != FIRST | LAST:
            raise ValueError('unexpected AAP handshake frame')
        return self.assembler.packet(0, fragment.data)

    def flush_handshake(self):
        while self.outgoing.pending:
            self.send_plain(3, self.outgoing.read(CHUNK_BYTES))

    def handshake(self, timeout=15):
        if self.ready:
            return
        deadline = time.monotonic() + timeout
        request = self.plain(deadline)
        if request.type != 1 or len(request.payload) != 4:
            raise ValueError('AAP version request expected')
        major, minor = struct.unpack('>HH', request.payload)
        compatible = major == 1 and minor >= 1
        self.send_plain(2, struct.pack('>HHH', 1, min(minor, 2), 0 if compatible else 65535))
        if not compatible:
            raise ValueError('unsupported AAP protocol version')
        while True:
            try:
                self.tls.do_handshake()
                self.flush_handshake()
                break
            except ssl.SSLWantReadError:
                self.flush_handshake()
                packet = self.plain(deadline)
                if packet.type != 3:
                    raise ValueError('AAP encapsulated TLS message expected')
                self.incoming.write(packet.payload)
        authentication = self.plain(deadline)
        if authentication.type != 4 or Message(authentication.payload).integer(1, signed=True) != 0:
            raise ValueError('head unit rejected Android Auto authentication')
        self.ready = True

    def send(self, channel, message_type, payload=b''):
        if not self.ready or self.stopped():
            raise RuntimeError('AAP transport is not active')
        data = struct.pack('>H', message_type) + payload
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError('AAP message exceeds limit')
        # Type 1 on a media channel is codec configuration. Its stream flags
        # must match media data so the receiver delivers it to the assembler.
        mode = ENCRYPTED | (CONTROL if channel != 0 and 2 <= message_type <= 26 else 0)
        for offset in range(0, len(data), CHUNK_BYTES):
            chunk = data[offset:offset + CHUNK_BYTES]
            if self.tls.write(chunk) != len(chunk):
                raise RuntimeError('incomplete AAP TLS write')
            encrypted = self.outgoing.read()
            flags = mode | (FIRST if offset == 0 else 0)
            if offset + len(chunk) == len(data):
                flags |= LAST
            total = len(data) if flags & (FIRST | LAST) == FIRST else None
            self.sock.sendall(frame(channel, flags, encrypted, total))

    def receive(self, timeout=.05):
        deadline = time.monotonic() + timeout
        while True:
            fragment = self.receive_fragment(max(0, deadline - time.monotonic()))
            if fragment is None:
                return None
            if not self.ready or not fragment.flags & ENCRYPTED:
                raise ValueError('encrypted AAP message expected')
            self.incoming.write(fragment.data)
            plaintext = bytearray()
            while True:
                try:
                    block = self.tls.read(CHUNK_BYTES)
                except ssl.SSLWantReadError:
                    break
                if not block:
                    raise EOFError('AAP TLS session closed')
                plaintext.extend(block)
                if len(plaintext) > 65535:
                    raise ValueError('AAP TLS plaintext exceeds fragment limit')
            if not plaintext:
                raise ValueError('AAP fragment contains no complete TLS application record')
            packet = self.assembler.add(fragment, bytes(plaintext))
            if packet is not None:
                return packet

    def close(self):
        self.ready = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
