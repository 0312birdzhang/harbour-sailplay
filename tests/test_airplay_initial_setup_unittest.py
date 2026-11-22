import ast
import importlib.util
import json
from pathlib import Path
import plistlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch

from carplay_proto import airplaydiscovery, airplaypair, airplaytiming, rtspclient, videodemo


source_path = Path(__file__).resolve().parents[1] / 'scripts' / 'wifi-session-probe.py'
spec = importlib.util.spec_from_file_location('airplay_initial_setup_probe', source_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
tree = ast.parse(source_path.read_text())
main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
connected = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == 'connected')
callback_code = compile(ast.Module(body=[connected], type_ignores=[]), str(source_path), 'exec')


class InitialSetupTests(unittest.TestCase):
    def test_start_session_updates_the_initial_configuration_for_the_same_hu(self):
        session = {'ssid': 'HU', 'passphrase': 'initial', 'addresses': []}
        update = json.dumps({'ssid': 'HU', 'passphrase': 'latest', 'addresses': ['fe80::1'], 'port': 7000})
        with patch('builtins.open', mock_open(read_data=update)):
            module.refresh_session('/fixture', session)
        self.assertEqual(session['passphrase'], 'latest')
        self.assertEqual(session['addresses'], ['fe80::1'])

    def test_unrelated_and_partially_written_sessions_preserve_the_current_hu(self):
        for raw in ('{"ssid":"Other","passphrase":"other"}', '{', '[]'):
            with self.subTest(raw=raw), patch('builtins.open', mock_open(read_data=raw)):
                session = {'ssid': 'HU', 'passphrase': 'initial'}
                module.refresh_session('/fixture', session)
                self.assertEqual(session, {'ssid': 'HU', 'passphrase': 'initial'})

    def run_attempts(self, setup_statuses, public_status=455, media_error=None,
                     peer_addresses=None, network_props=None, discovered_endpoints=None,
                     connect_errors=()):
        info = plistlib.dumps({'model': 'Fiat CARLINE_13'}, fmt=plistlib.FMT_BINARY)
        setup = plistlib.dumps({'eventPort': 7001, 'timingPort': 7002}, fmt=plistlib.FMT_BINARY)
        clients = []
        for status in setup_statuses:
            client = Mock()
            client.request.side_effect = [(public_status, {}, info),
                (status, {'Server': 'AirPlay/320.17.3'}, setup if status == 200 else b''),
                (200, {}, info)]
            clients.append(client)
        timings = [Mock(port=7002) for _ in setup_statuses]
        service = Mock()
        service.GetProperties.return_value = {'Ethernet': {'Interface': 'wlan0'}}
        service.GetProperties.return_value.update(network_props or {})
        if peer_addresses is None:
            peer_addresses = ['192.168.3.' + str(index + 1) for index in range(len(clients))]
        loop = Mock()
        namespace = module.__dict__.copy()
        namespace.update(session_started=module.time.monotonic(),
                         wpa2_retry=SimpleNamespace(started=False), media_lease=Mock(),
                         restore_clock='/tmp/unused-setup-clock', service=Mock(return_value=service),
                         target='/net/connman/service/test', loop=loop, phone_name='SailfishOS',
                         args=SimpleNamespace(sustained=False), collection_enabled=lambda: False,
                         socket_endpoint=lambda sock, method: ('192.168.3.100', 5000),
                         airplay_iap_link=Mock(), session={
                             'addresses': peer_addresses,
                             'port': 7000, 'passphrase': 'fixture-passphrase',
                             'bluetooth_address': '50:56:A8:06:20:5E',
                         })
        exec(callback_code, namespace)
        identity = json.dumps({'id': 'fixture-identity', 'private_key': '00' * 32})
        lease = (network_props or {}).get('IPv4', {}).get('Address')
        with patch.object(rtspclient, 'connect', side_effect=list(connect_errors) + clients) as connections, \
                patch.object(airplaydiscovery, 'discover', return_value=discovered_endpoints or []), \
                patch.object(airplaydiscovery, 'interface_address', return_value=lease), \
                patch.object(airplaypair, 'pair_setup'), \
                patch.object(airplaypair, 'pair_verify', return_value=SimpleNamespace(shared=b'shared')), \
                patch.object(airplaytiming, 'TimingServer', side_effect=timings), \
                patch.object(videodemo, 'run_demo', side_effect=media_error) as media, \
                patch.object(module.os, 'utime'), patch.object(module.os.path, 'exists', return_value=True), \
                patch('builtins.open', mock_open(read_data=identity)), patch('builtins.print') as messages:
            namespace['connected']()
        loop.quit.assert_called_once()
        for client, timing in zip(clients, timings):
            client.sock.close.assert_called_once()
            timing.close.assert_called_once()
        output = '\n'.join(str(call.args[0]) for call in messages.call_args_list)
        return media, output, connections

    def test_rejected_setup_preserves_receiver_info_and_does_not_start_media(self):
        for status in (400, 500):
            with self.subTest(status=status):
                media, output, _ = self.run_attempts([status])
                media.assert_not_called()
                self.assertIn("AirPlay model='Fiat CARLINE_13'", output)
                self.assertIn('AirPlay probe failed stage=initial-setup', output)
                self.assertIn('Encrypted initial SETUP rejected status=' + str(status), output)
                self.assertNotIn('UnboundLocalError', output)

    def test_public_info_response_still_pairs_and_uses_successful_setup(self):
        for status in (200, 455):
            with self.subTest(public_status=status):
                media, output, _ = self.run_attempts([200], public_status=status)
                media.assert_called_once()
                self.assertEqual(media.call_args.args[4], {'eventPort': 7001, 'timingPort': 7002})
                self.assertNotIn('AirPlay probe failed', output)

    def test_rejected_second_address_cannot_reuse_first_address_setup(self):
        media, output, _ = self.run_attempts([200, 400], media_error=EOFError('fixture media failure'))
        media.assert_called_once()
        self.assertIn('Encrypted initial SETUP rejected status=400', output)
        self.assertNotIn('UnboundLocalError', output)

    def test_no_iap2_address_or_dhcp_gateway_reaches_airplay_and_media_on_the_first_host(self):
        media, output, connections = self.run_attempts([200], peer_addresses=[],
            network_props={'IPv4': {'Address': '192.168.3.100', 'Netmask': '255.255.255.0'}},
            discovered_endpoints=[('192.168.3.2', 12345)])
        connections.assert_called_once_with('192.168.3.1', 7000, 'wlan0', bind_device=True, source_address_wait=5,
                                            refused_wait=15)
        media.assert_called_once()
        self.assertIn('trying first host of leased network address=192.168.3.1', output)
        self.assertNotIn('discovering on interface', output)

    def test_unreachable_first_host_reaches_airplay_and_media_through_discovery(self):
        media, output, connections = self.run_attempts([200], peer_addresses=[],
            network_props={'IPv4': {'Address': '192.168.50.102', 'Netmask': '255.255.255.0'}},
            discovered_endpoints=[('192.168.50.2', 12345)],
            connect_errors=[OSError(113, 'fixture: no route to host')])
        self.assertEqual([call.args[:2] for call in connections.call_args_list],
                         [('192.168.50.1', 7000), ('192.168.50.2', 12345)])
        media.assert_called_once()
        self.assertIn('AirPlay probe failed stage=control-connect', output)
        self.assertIn('AirPlay peer address absent from iAP2 and DHCP; discovering on interface=wlan0', output)

    def test_no_discovered_endpoint_retires_the_worker_with_discovery_context(self):
        media, output, connections = self.run_attempts([], peer_addresses=[])
        media.assert_not_called()
        connections.assert_not_called()
        self.assertIn('AirPlay peer address absent from iAP2 and DHCP', output)
