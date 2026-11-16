import errno
import ipaddress
import socket
import struct
import unittest
from unittest.mock import ANY, Mock, patch

from carplay_proto import airplaydiscovery, rtspclient


def dns_name(name):
    return b''.join(bytes([len(label)]) + label.encode('ascii')
                    for label in name.split('.')) + b'\0'


def dns_record(name, kind, data, ttl=120, record_class=0x8001):
    owner = dns_name(name) if isinstance(name, str) else name
    return owner + struct.pack('!HHIH', kind, record_class, ttl, len(data)) + data


def dns_response(*records):
    return struct.pack('!6H', 0, 0x8400, 0, len(records), 0, 0) + b''.join(records)


SERVICE = '_airplay._tcp.local'
INSTANCE = 'HU.' + SERVICE
HOST = 'receiver.local'
SRV_DATA = struct.pack('!3H', 0, 0, 12345) + dns_name(HOST)
ADDRESS_DATA = ipaddress.ip_address('192.0.2.2').packed


class DnsResponseTests(unittest.TestCase):
    def test_compressed_answer_and_additional_records_resolve_the_advertised_port(self):
        question = dns_name(SERVICE) + struct.pack('!HH', 12, 1)
        instance_offset = 12 + len(question) + 2 + 10
        pointer = dns_record(b'\xc0\x0c', 12, b'\x02HU\xc0\x0c')
        srv_owner = struct.pack('!H', 0xc000 | instance_offset)
        srv = dns_record(srv_owner, 33, SRV_DATA)
        host_offset = 12 + len(question) + len(pointer) + 2 + 10 + 6
        address_owner = struct.pack('!H', 0xc000 | host_offset)
        address = dns_record(address_owner, 1, ADDRESS_DATA)
        packet = struct.pack('!6H', 0, 0x8400, 1, 1, 0, 2) + question + pointer + srv + address
        records = airplaydiscovery.parse_response(packet)
        self.assertEqual(airplaydiscovery.receiver_endpoints(records), [('192.0.2.2', 12345)])
        self.assertEqual(records[0].value, (b'hu', b'_airplay', b'_tcp', b'local'))

    def test_ipv6_and_multiple_addresses_are_retained_without_duplicates(self):
        packet = dns_response(dns_record(INSTANCE, 33, SRV_DATA),
            dns_record(HOST, 1, ADDRESS_DATA), dns_record(HOST, 1, ADDRESS_DATA),
            dns_record(HOST, 28, ipaddress.ip_address('fe80::abcd').packed))
        endpoints = airplaydiscovery.receiver_endpoints(airplaydiscovery.parse_response(packet))
        self.assertEqual(endpoints, [('192.0.2.2', 12345), ('fe80::abcd', 12345)])

    def test_carplay_service_and_case_insensitive_names_are_supported(self):
        packet = dns_response(dns_record('HU._CARPLAY._TCP.LOCAL', 33, SRV_DATA),
                              dns_record('RECEIVER.LOCAL', 1, ADDRESS_DATA))
        self.assertEqual(airplaydiscovery.receiver_endpoints(airplaydiscovery.parse_response(packet)),
                         [('192.0.2.2', 12345)])

    def test_unrelated_services_and_goodbye_records_are_not_receivers(self):
        for owner, ttl in (('HU._http._tcp.local', 120), (INSTANCE, 0)):
            with self.subTest(owner=owner, ttl=ttl):
                packet = dns_response(dns_record(owner, 33, SRV_DATA, ttl=ttl),
                                      dns_record(HOST, 1, ADDRESS_DATA))
                self.assertEqual(airplaydiscovery.receiver_endpoints(
                    airplaydiscovery.parse_response(packet)), [])

    def test_invalid_addresses_and_zero_port_are_not_probed(self):
        for address in ('0.0.0.0', '127.0.0.1', '224.0.0.251', '::', '::1', 'ff02::fb'):
            with self.subTest(address=address):
                ip = ipaddress.ip_address(address)
                packet = dns_response(dns_record(INSTANCE, 33, SRV_DATA),
                                      dns_record(HOST, 1 if ip.version == 4 else 28, ip.packed))
                self.assertEqual(airplaydiscovery.receiver_endpoints(
                    airplaydiscovery.parse_response(packet)), [])
        packet = dns_response(dns_record(INSTANCE, 33, struct.pack('!3H', 0, 0, 0) + dns_name(HOST)),
                              dns_record(HOST, 1, ADDRESS_DATA))
        self.assertEqual(airplaydiscovery.receiver_endpoints(airplaydiscovery.parse_response(packet)), [])

    def test_truncation_and_compression_cycles_are_rejected(self):
        packets = [b'', b'\0' * 11, dns_response(b'\xc0\x0c'),
                   dns_response(dns_record(SERVICE, 12, b'\xc0\xff')),
                   dns_response(dns_record(HOST, 1, b'\0' * 3)),
                   dns_response(dns_record(INSTANCE, 33, b'\0' * 6)),
                   dns_response(dns_record(SERVICE, 12, dns_name(INSTANCE) + b'\0'))]
        complete = dns_response(dns_record(INSTANCE, 33, SRV_DATA), dns_record(HOST, 1, ADDRESS_DATA))
        packets.extend(complete[:size] for size in range(12, len(complete)))
        for packet in packets:
            with self.subTest(size=len(packet)):
                with self.assertRaises(ValueError):
                    airplaydiscovery.parse_response(packet)

    def test_dns_queries_and_error_responses_are_rejected(self):
        for flags in (0, 0x8003, 0x8800):
            with self.subTest(flags=flags):
                with self.assertRaises(ValueError):
                    airplaydiscovery.parse_response(struct.pack('!6H', 0, flags, 0, 0, 0, 0))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.props = {'Ethernet': {'Interface': 'wlan0'},
                      'IPv4': {'Address': '192.168.50.102', 'Netmask': '255.255.255.0'}}

    def test_dhcp_without_gateway_discovers_an_endpoint_and_uses_its_srv_port(self):
        with patch.object(airplaydiscovery, 'discover', return_value=[('192.168.50.2', 12345)]) as discover:
            self.assertEqual(list(airplaydiscovery.endpoints([], 7000, self.props, log=Mock())),
                             [('192.168.50.2', 12345)])
        discover.assert_called_once_with('wlan0', log=ANY)

    def test_empty_gateway_value_allows_discovery(self):
        for gateway in (None, ''):
            with self.subTest(gateway=gateway):
                self.props['IPv4']['Gateway'] = gateway
                with patch.object(airplaydiscovery, 'discover', return_value=[('192.168.50.2', 12345)]):
                    self.assertEqual(list(airplaydiscovery.endpoints([], 7000, self.props, log=Mock())),
                                     [('192.168.50.2', 12345)])

    def test_existing_iap2_and_gateway_addresses_keep_the_negotiated_port(self):
        self.props['IPv4']['Gateway'] = '192.0.2.2'
        with patch.object(airplaydiscovery, 'discover') as discover:
            self.assertEqual(list(airplaydiscovery.endpoints(['192.0.2.2', 'fe80::abcd%wlan0'],
                                                           7000, self.props)),
                             [('192.0.2.2', 7000), ('fe80::abcd', 7000)])
        discover.assert_not_called()

    def test_gateway_only_handover_keeps_the_existing_behavior(self):
        self.props['IPv4']['Gateway'] = '192.0.2.2'
        with patch.object(airplaydiscovery, 'discover') as discover:
            self.assertEqual(list(airplaydiscovery.endpoints([], 7000, self.props)), [('192.0.2.2', 7000)])
        discover.assert_not_called()

    def test_invalid_explicit_peers_do_not_trigger_discovery(self):
        with patch.object(airplaydiscovery, 'discover') as discover:
            self.assertEqual(list(airplaydiscovery.endpoints(['localhost', '127.0.0.1', '::'], 7000,
                                                           self.props)), [])
        discover.assert_not_called()

    def test_discovery_socket_errors_are_logged(self):
        log = Mock()
        with patch.object(airplaydiscovery, 'discover', side_effect=OSError(errno.ENODEV, 'no interface')):
            self.assertEqual(list(airplaydiscovery.endpoints([], 7000, self.props, log=log)), [])
        self.assertTrue(any('endpoint discovery failed' in call.args[0] for call in log.call_args_list))


class DiscoveryTransportTests(unittest.TestCase):
    def run_discovery(self, packets, timeout=2):
        sock = Mock()
        sock.recvfrom.side_effect = packets
        now = [0.0]
        remaining = [len(packets)]
        def readable(sockets, writers, errors, wait):
            if remaining[0]:
                remaining[0] -= 1
                now[0] += min(0.1, wait)
                return [sock], [], []
            now[0] += wait
            return [], [], []
        log = Mock()
        with patch.object(airplaydiscovery.socket, 'if_nametoindex', return_value=7), \
                patch.object(airplaydiscovery.socket, 'socket', side_effect=[sock, OSError(errno.EAFNOSUPPORT, 'IPv6 disabled')]), \
                patch.object(airplaydiscovery.select, 'select', side_effect=readable), \
                patch.object(airplaydiscovery.time, 'monotonic', side_effect=lambda: now[0]):
            result = airplaydiscovery.discover('wlan0', timeout=timeout, log=log)
        sock.close.assert_called_once()
        return result, sock, log, now[0]

    def test_split_ptr_srv_and_address_responses_are_resolved_on_the_hu_interface(self):
        packets = [(dns_response(dns_record(SERVICE, 12, dns_name(INSTANCE))), ('192.0.2.2', 5353)),
                   (dns_response(dns_record(INSTANCE, 33, SRV_DATA)), ('192.0.2.2', 5353)),
                   (dns_response(dns_record(HOST, 1, ADDRESS_DATA)), ('192.0.2.2', 5353))]
        result, sock, _, _ = self.run_discovery(packets)
        self.assertEqual(result, [('192.0.2.2', 12345)])
        sock.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b'wlan0\0')
        sock.bind.assert_called_once_with(('', 0))
        self.assertEqual(sock.sendto.call_count, 3)
        for call in sock.sendto.call_args_list:
            self.assertEqual(call.args[1], ('224.0.0.251', 5353))
            data = call.args[0]
            count = struct.unpack('!H', data[4:6])[0]
            offset = 12
            for _ in range(count):
                _, offset = airplaydiscovery._read_name(data, offset)
                _, query_class = struct.unpack('!HH', data[offset:offset + 4])
                self.assertEqual(query_class, 0x8001)
                offset += 4

    def test_timeout_is_bounded_and_records_the_missing_receiver(self):
        result, sock, log, elapsed = self.run_discovery([])
        self.assertEqual(result, [])
        self.assertEqual(elapsed, 2)
        self.assertEqual(sock.sendto.call_count, 2)
        self.assertTrue(any('reason=no-mDNS-receiver' in call.args[0] for call in log.call_args_list))

    def test_bad_packets_and_responses_from_other_ports_do_not_end_discovery(self):
        response = dns_response(dns_record(INSTANCE, 33, SRV_DATA), dns_record(HOST, 1, ADDRESS_DATA))
        result, _, log, _ = self.run_discovery([(b'bad', ('192.0.2.2', 5353)),
                                               (response, ('192.0.2.2', 53)),
                                               (response, ('192.0.2.2', 5353))])
        self.assertEqual(result, [('192.0.2.2', 12345)])
        self.assertTrue(any('response ignored' in call.args[0] for call in log.call_args_list))

    def test_goodbye_srv_is_removed_before_a_later_address_response(self):
        packets = [(dns_response(dns_record(INSTANCE, 33, SRV_DATA)), ('192.0.2.2', 5353)),
                   (dns_response(dns_record(INSTANCE, 33, SRV_DATA, ttl=0)), ('192.0.2.2', 5353)),
                   (dns_response(dns_record(HOST, 1, ADDRESS_DATA)), ('192.0.2.2', 5353))]
        result, _, _, _ = self.run_discovery(packets)
        self.assertEqual(result, [])

    def test_ipv6_only_discovery_scopes_multicast_to_the_hu_interface(self):
        sock = Mock()
        response = dns_response(dns_record(INSTANCE, 33, SRV_DATA),
                                dns_record(HOST, 28, ipaddress.ip_address('fe80::abcd').packed))
        sock.recvfrom.return_value = (response, ('fe80::abcd', 5353, 0, 7))
        with patch.object(airplaydiscovery.socket, 'if_nametoindex', return_value=7), \
                patch.object(airplaydiscovery.socket, 'socket', side_effect=[OSError(errno.EAFNOSUPPORT, 'IPv4 disabled'), sock]), \
                patch.object(airplaydiscovery.select, 'select', return_value=([sock], [], [])):
            self.assertEqual(airplaydiscovery.discover('wlan0', log=Mock()), [('fe80::abcd', 12345)])
        sock.setsockopt.assert_any_call(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, 7)
        sock.sendto.assert_called_once_with(ANY, ('ff02::fb', 5353, 0, 7))
        sock.close.assert_called_once()


class BoundControlTests(unittest.TestCase):
    def test_handover_control_socket_binds_the_target_wifi_before_connecting(self):
        sock = Mock()
        with patch.object(rtspclient.socket, 'socket', return_value=sock):
            client = rtspclient.connect('192.0.2.2', 12345, 'wlan0', bind_device=True)
        self.assertIs(client.sock, sock)
        sock.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b'wlan0\0')
        sock.connect.assert_called_once_with(('192.0.2.2', 12345))

    def test_existing_connect_callers_keep_the_default_socket_behavior(self):
        sock = Mock()
        with patch.object(rtspclient.socket, 'socket', return_value=sock):
            rtspclient.connect('192.0.2.2', 7000, 'wlan0')
        sock.setsockopt.assert_not_called()

    def test_binding_failure_closes_the_socket(self):
        sock = Mock()
        sock.setsockopt.side_effect = OSError(errno.ENODEV, 'no interface')
        with patch.object(rtspclient.socket, 'socket', return_value=sock):
            with self.assertRaises(OSError):
                rtspclient.connect('192.0.2.2', 7000, 'wlan0', bind_device=True)
        sock.close.assert_called_once()
        sock.connect.assert_not_called()

    def test_ipv6_control_uses_the_selected_wifi_scope(self):
        sock = Mock()
        with patch.object(rtspclient.socket, 'socket', return_value=sock), \
                patch.object(rtspclient.socket, 'if_nametoindex', return_value=7):
            rtspclient.connect('fe80::abcd%wlan0', 12345, 'wlan0', bind_device=True)
        sock.connect.assert_called_once_with(('fe80::abcd', 12345, 0, 7))
