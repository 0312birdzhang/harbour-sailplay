"""Find a local AirPlay receiver when iAP2 and DHCP supply no peer address."""
import collections
import ipaddress
import select
import socket
import struct
import time


SERVICES = ((b'_airplay', b'_tcp', b'local'),
            (b'_carplay', b'_tcp', b'local'))
Record = collections.namedtuple('Record', 'name kind value ttl')


def _read_name(packet, offset):
    labels = []
    visited = set()
    next_offset = None
    wire_size = 1
    while True:
        if offset >= len(packet) or offset in visited:
            raise ValueError('truncated or cyclic DNS name')
        visited.add(offset)
        length = packet[offset]
        if length & 0xc0 == 0xc0:
            if offset + 1 >= len(packet):
                raise ValueError('truncated DNS pointer')
            if next_offset is None:
                next_offset = offset + 2
            offset = ((length & 0x3f) << 8) | packet[offset + 1]
            continue
        if length & 0xc0:
            raise ValueError('invalid DNS label')
        offset += 1
        if not length:
            return tuple(labels), next_offset if next_offset is not None else offset
        if offset + length > len(packet):
            raise ValueError('truncated DNS label')
        labels.append(packet[offset:offset + length].lower())
        wire_size += length + 1
        if wire_size > 255:
            raise ValueError('oversized DNS name')
        offset += length


def parse_response(packet):
    if len(packet) < 12:
        raise ValueError('truncated DNS header')
    _, flags, questions, answers, authority, additional = struct.unpack('!6H', packet[:12])
    if not flags & 0x8000 or flags & 0x780f:
        raise ValueError('unsuccessful DNS response')
    offset = 12
    for _ in range(questions):
        _, offset = _read_name(packet, offset)
        offset += 4
        if offset > len(packet):
            raise ValueError('truncated DNS question')
    records = []
    for _ in range(answers + authority + additional):
        name, offset = _read_name(packet, offset)
        if offset + 10 > len(packet):
            raise ValueError('truncated DNS record')
        kind, record_class, ttl, size = struct.unpack('!HHIH', packet[offset:offset + 10])
        offset += 10
        end = offset + size
        if end > len(packet):
            raise ValueError('truncated DNS record data')
        value = None
        if record_class & 0x7fff == 1:
            if kind in (1, 28):
                if size != (4 if kind == 1 else 16):
                    raise ValueError('invalid DNS address size')
                value = str(ipaddress.ip_address(packet[offset:end]))
            elif kind == 12:
                value, consumed = _read_name(packet, offset)
                if consumed != end:
                    raise ValueError('invalid DNS PTR data')
            elif kind == 33:
                if size < 7:
                    raise ValueError('truncated DNS SRV data')
                priority, weight, port = struct.unpack('!3H', packet[offset:offset + 6])
                target, consumed = _read_name(packet, offset + 6)
                if consumed != end:
                    raise ValueError('invalid DNS SRV target')
                value = (priority, weight, port, target)
        if value is not None:
            records.append(Record(name, kind, value, ttl))
        offset = end
    return records


def _query(questions):
    packet = struct.pack('!6H', 0, 0, len(questions), 0, 0, 0)
    for name, kind in sorted(questions):
        packet += b''.join(bytes([len(label)]) + label for label in name) + b'\0'
        # The ephemeral source port and QU flag request a unicast reply.
        packet += struct.pack('!HH', kind, 0x8001)
    return packet


def receiver_endpoints(records):
    servers = [record for record in records if record.kind == 33 and record.ttl
               and len(record.name) > 3 and record.name[-3:] in SERVICES]
    servers.sort(key=lambda record: record.value[0])
    result = []
    for server in servers:
        _, _, port, target = server.value
        if not port:
            continue
        for record in records:
            if record.kind not in (1, 28) or not record.ttl or record.name != target:
                continue
            address = ipaddress.ip_address(record.value)
            if address.is_unspecified or address.is_loopback or address.is_multicast:
                continue
            endpoint = (str(address), port)
            if endpoint not in result:
                result.append(endpoint)
    return result[:8]


def discover(interface, timeout=5, log=print):
    log('AirPlay mDNS discovery started interface={} timeoutSeconds={}'.format(interface, timeout))
    index = socket.if_nametoindex(interface)
    transports = []
    records = {}
    questions = {(name, 12) for name in SERVICES}
    deadline = time.monotonic() + timeout
    next_query = 0
    try:
        for family in (socket.AF_INET, socket.AF_INET6):
            try:
                sock = socket.socket(family, socket.SOCK_DGRAM)
            except OSError as error:
                log('AirPlay mDNS socket unavailable family={} errno={}'.format(family, error.errno))
                continue
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b'\0')
                if family == socket.AF_INET:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                    struct.pack('=4s4si', b'\0' * 4, b'\0' * 4, index))
                    sock.bind(('', 0))
                    destination = ('224.0.0.251', 5353)
                else:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 255)
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, index)
                    sock.bind(('::', 0))
                    destination = ('ff02::fb', 5353, 0, index)
                sock.setblocking(False)
            except OSError as error:
                log('AirPlay mDNS interface unavailable family={} errno={}'.format(family, error.errno))
                sock.close()
                continue
            transports.append((sock, destination))
        while transports and time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_query:
                query = _query(questions)
                for sock, destination in transports:
                    try:
                        sock.sendto(query, destination)
                    except OSError as error:
                        log('AirPlay mDNS query failed destination={} errno={}'.format(destination[0], error.errno))
                next_query = now + 1
            ready, _, _ = select.select([sock for sock, _ in transports], [], [],
                                        max(0, min(1, deadline - time.monotonic())))
            for sock in ready:
                try:
                    packet, peer = sock.recvfrom(65535)
                    if peer[1] != 5353:
                        continue
                    response = parse_response(packet)
                except (OSError, ValueError) as error:
                    log('AirPlay mDNS response ignored error={}'.format(type(error).__name__))
                    continue
                now = time.monotonic()
                for record in response:
                    key = (record.name, record.kind, record.value)
                    if record.ttl:
                        records[key] = (record, now + record.ttl)
                    else:
                        records.pop(key, None)
                current = [record for record, expires in records.values() if expires > now]
                endpoints = receiver_endpoints(current)
                if endpoints:
                    log('AirPlay mDNS receiver discovered interface={} endpoints={}'.format(interface, endpoints))
                    return endpoints
                previous = len(questions)
                for record in current:
                    if record.kind == 12 and record.name in SERVICES and record.value[-3:] in SERVICES:
                        questions.add((record.value, 33))
                    elif record.kind == 33 and record.name[-3:] in SERVICES:
                        questions.add((record.value[3], 1))
                        questions.add((record.value[3], 28))
                if len(questions) != previous:
                    next_query = 0
    finally:
        for sock, _ in transports:
            sock.close()
    log('AirPlay endpoint discovery failed interface={} reason=no-mDNS-receiver'.format(interface))
    return []


def subnet_peer(ipv4):
    """Guess the access point when DHCP supplied an address but no router.

    A head unit is its own access point and DHCP server, conventionally the
    first host of the network it leases.  The guess is only a candidate: the
    caller still has to pair with whatever answers there.
    """
    try:
        network = ipaddress.ip_interface('{}/{}'.format(
            ipv4.get('Address'), ipv4.get('Netmask'))).network
    except ValueError:
        return None
    if network.version != 4 or not 16 <= network.prefixlen <= 30:
        return None
    peer = network.network_address + 1
    if str(peer) == str(ipv4.get('Address')):
        return None
    return str(peer)


# A guessed peer is only followed by mDNS while this handover is still young.
GUESS_DISCOVERY_WINDOW = 30


def interface_address(interface):
    """Current IPv4 address of an interface, or None."""
    import fcntl
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            raw = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack('256s', interface.encode()[:15]))
        return socket.inet_ntoa(raw[20:24])
    except OSError:
        return None


def endpoints(addresses, port, props, log=print):
    known = list(addresses)
    ipv4 = props.get('IPv4', {})
    gateway = str(ipv4.get('Gateway') or '')
    if gateway:
        known.append(gateway)
    guessed = False
    if not known:
        peer = subnet_peer(ipv4)
        if peer:
            log('AirPlay peer address absent from iAP2 and DHCP; trying first host of leased network address={}'.format(peer))
            known.append(peer)
            guessed = True
    handed_out = time.monotonic()
    seen = set()
    for candidate in known:
        try:
            address = ipaddress.ip_address(str(candidate).split('%')[0])
        except ValueError:
            continue
        if address.is_unspecified or address.is_loopback or address.is_multicast or address in seen:
            continue
        seen.add(address)
        yield str(address), int(port)
    if known and not guessed:
        return
    interface = str(props.get('Ethernet', {}).get('Interface', ''))
    if guessed:
        # Control returns here after the caller is done with the guess.  If a
        # session ran, or Wi-Fi has gone back to another network, discovering
        # now would find unrelated AirPlay receivers on that network.
        if time.monotonic() - handed_out > GUESS_DISCOVERY_WINDOW:
            return
        if interface_address(interface) != str(ipv4.get('Address')):
            log('AirPlay discovery skipped; interface={} no longer holds the head unit lease'.format(interface))
            return
    log('AirPlay peer address absent from iAP2 and DHCP; discovering on interface={}'.format(interface))
    try:
        for address, discovered_port in discover(interface, log=log):
            try:
                if ipaddress.ip_address(str(address).split('%')[0]) in seen and int(discovered_port) == int(port):
                    continue
            except ValueError:
                pass
            yield address, discovered_port
    except OSError as error:
        log('AirPlay endpoint discovery failed interface={} errno={}'.format(interface, error.errno))
