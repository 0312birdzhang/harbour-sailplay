"""Discover dynamic Android Auto SDP services without disconnecting Bluetooth."""
import ctypes
import errno
import logging
import os
import socket
import select
import struct
import time

from .bluez import supports
from .wireless import AA_UUID
from carplay_proto.bluezadapter import resolve_device


AF_BLUETOOTH = 31
BTPROTO_L2CAP = 0
BTPROTO_RFCOMM = 3
SOL_BLUETOOTH = 274
BT_SECURITY = 4
BT_SECURITY_MEDIUM = 2
MAX_SDP_BYTES = 8192
AA_SERVICE = bytes.fromhex(AA_UUID.replace('-', ''))


def connect_bluetooth(local, remote, channel, protocol, timeout=3):
    """Linux Python builds can omit Bluetooth sockaddr support. Use libc for it."""
    def address(mac, port):
        identity = bytes.fromhex(mac.replace(':', ''))[::-1]
        if len(identity) != 6:
            raise ValueError('invalid Bluetooth address')
        if protocol == BTPROTO_L2CAP:
            return struct.pack('<HH6sHBx', AF_BLUETOOTH, port, identity, 0, 0)
        return struct.pack('<H6sBx', AF_BLUETOOTH, identity, port)

    kind = socket.SOCK_SEQPACKET if protocol == BTPROTO_L2CAP else socket.SOCK_STREAM
    peer = socket.socket(AF_BLUETOOTH, kind, protocol)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        peer.settimeout(timeout)
        if protocol == BTPROTO_RFCOMM:
            peer.setsockopt(SOL_BLUETOOTH, BT_SECURITY, bytes([BT_SECURITY_MEDIUM, 0]))
        value = address(local, 0)
        if libc.bind(peer.fileno(), value, len(value)) != 0:
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number))
        value = address(remote, channel)
        if libc.connect(peer.fileno(), value, len(value)) != 0:
            number = ctypes.get_errno()
            if number not in (errno.EINPROGRESS, errno.EALREADY, errno.EINTR):
                raise OSError(number, os.strerror(number))
            _, writable, exceptional = select.select([], [peer], [peer], timeout)
            if not writable and not exceptional:
                raise TimeoutError('Bluetooth connection timed out')
            number = peer.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if number:
                raise OSError(number, os.strerror(number))
        return peer
    except Exception:
        peer.close()
        raise


def sdp_element(data, offset=0, depth=0):
    if offset >= len(data) or depth > 8:
        raise ValueError('invalid SDP data element')
    descriptor = data[offset]
    kind, size_index = descriptor >> 3, descriptor & 7
    offset += 1
    if size_index < 5:
        size = 0 if kind == 0 else 1 << size_index
    else:
        length_bytes = 1 << (size_index - 5)
        if offset + length_bytes > len(data):
            raise ValueError('truncated SDP element length')
        size = int.from_bytes(data[offset:offset + length_bytes], 'big')
        offset += length_bytes
    end = offset + size
    if end > len(data):
        raise ValueError('truncated SDP element')
    value = data[offset:end]
    if kind == 6:
        value = []
        while offset < end:
            element, offset = sdp_element(data[:end], offset, depth + 1)
            value.append(element)
    elif kind in (1, 3):
        value = int.from_bytes(value, 'big')
    return (kind, value), end


def rfcomm_channel(attributes):
    root, end = sdp_element(attributes)
    if end != len(attributes) or root[0] != 6:
        raise ValueError('invalid SDP service attribute list')
    for kind, record in root[1]:
        if kind != 6 or len(record) % 2:
            raise ValueError('invalid SDP service record')
        values = {}
        for index in range(0, len(record), 2):
            attribute, value = record[index:index + 2]
            if attribute[0] != 1:
                raise ValueError('invalid SDP attribute identifier')
            values[attribute[1]] = value
        classes = values.get(1, (6, []))
        if classes[0] != 6 or (3, int.from_bytes(AA_SERVICE, 'big')) not in classes[1]:
            continue
        protocols = values.get(4, (6, []))
        if protocols[0] != 6:
            continue
        for kind, descriptor in protocols[1]:
            if kind == 6 and len(descriptor) >= 2 and descriptor[0] == (3, 3):
                kind, channel = descriptor[1]
                if kind == 1 and 1 <= channel <= 30:
                    return channel
    return None


def find_channel(local, remote, timeout=3):
    attributes = bytearray()
    continuation = b'\x00'
    with connect_bluetooth(local, remote, 1, BTPROTO_L2CAP, timeout) as peer:
        deadline = time.monotonic() + timeout
        for transaction in range(1, 17):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('SDP discovery timed out')
            peer.settimeout(remaining)
            parameters = b'\x35\x11\x1c' + AA_SERVICE + b'\x20\x00\x35\x05\x0a\x00\x00\xff\xff' + continuation
            peer.sendall(struct.pack('!BHH', 6, transaction, len(parameters)) + parameters)
            response = peer.recv(MAX_SDP_BYTES + 5)
            if len(response) < 8:
                raise ValueError('truncated SDP response')
            pdu, identifier, length = struct.unpack_from('!BHH', response)
            if pdu != 7 or identifier != transaction or length != len(response) - 5:
                raise ValueError('invalid SDP response header')
            count = struct.unpack_from('!H', response, 5)[0]
            state = 7 + count
            if state >= len(response) or response[state] > 16 or state + 1 + response[state] != len(response):
                raise ValueError('invalid SDP continuation state')
            attributes.extend(response[7:state])
            if len(attributes) > MAX_SDP_BYTES:
                raise ValueError('SDP service attributes exceed limit')
            continuation = response[state:]
            if continuation == b'\x00':
                return rfcomm_channel(bytes(attributes))
    raise ValueError('SDP continuation limit exceeded')


def discover_head_units(objects, adapter, stop=None, known_device=None):
    """Enrich this snapshot with freshly proven services, leaving BlueZ state intact."""
    current, channels = dict(objects), {}
    known_device = resolve_device(objects, known_device)
    local = str(objects[adapter]['org.bluez.Adapter1']['Address'])
    for path, interfaces in objects.items():
        properties = interfaces.get('org.bluez.Device1', {})
        if (not str(path).startswith(adapter + '/') or not properties.get('Paired')
                or (not properties.get('Connected') and str(path) != known_device)
                or (properties.get('Connected') and supports(properties, AA_UUID))):
            continue
        if stop is not None and stop.is_set():
            break
        try:
            channel = find_channel(local, str(properties['Address']))
        except (OSError, ValueError):
            logging.debug('Android Auto SDP lookup unavailable device=%s', path, exc_info=True)
            continue
        if channel is not None:
            logging.info('Android Auto live SDP discovered device=%s channel=%d', path, channel)
            updated = dict(properties)
            if not supports(properties, AA_UUID):
                updated['UUIDs'] = list(properties.get('UUIDs', [])) + [AA_UUID]
            current[path] = dict(interfaces, **{'org.bluez.Device1': updated})
            channels[str(path)] = channel
    return current, channels
