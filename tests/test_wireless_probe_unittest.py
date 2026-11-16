"""Exercise the executable against a mock accessory, including retransmission."""
import ast
import importlib.util
import os
import socket
import threading
import unittest
import tempfile
import fcntl
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import Mock, patch

from carplay_proto.iap2link import ACK, DETECT, SYN, Decoder, Packet, encode, synchronization
from carplay_proto.wire import Frame, encode_param

path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'wireless-probe.py')
spec = importlib.util.spec_from_file_location('wireless_probe', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProfileRetryTests(unittest.TestCase):
    def setUp(self):
        with open(path) as source:
            tree = ast.parse(source.read())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        connect = next(node for node in ast.walk(main)
                       if isinstance(node, ast.FunctionDef) and node.name == 'connect')
        self.code = compile(ast.Module(body=[connect], type_ignores=[]), path, 'exec')
        self.target = '/org/bluez/hci1/dev_fixture'
        self.device = Mock()
        self.device.Get.return_value = True
        self.objects = Mock()
        self.objects.GetManagedObjects.return_value = {
            self.target: {'org.bluez.Device1': {'Connected': True}}}
        bus = Mock()
        bus.get_object.side_effect = lambda name, object_path: self.objects if object_path == '/' else self.device
        self.thread = Mock(name='worker')
        self.thread.name = 'RFCOMM-client'
        self.thread.is_alive.return_value = False
        self.worker = (Mock(), self.thread, Mock())
        self.manager = Mock()
        class DbusError(Exception):
            def get_dbus_name(self):
                return 'fixture.Error'
        self.error = DbusError
        self.namespace = dict(module.__dict__, bus=bus,
            dbus=SimpleNamespace(Interface=lambda obj, interface: obj, DBusException=DbusError),
            args=SimpleNamespace(device=self.target), adapter='/org/bluez/hci1',
            workers={self.target: self.worker}, connecting=[False], last_state=[None, 0],
            select_head_unit=Mock(return_value=self.target), previous_head_unit=Mock(),
            media_active=Mock(return_value=False), manager=self.manager,
            retire_worker=Mock(), profile_power=Mock(), loop=Mock())
        exec(self.code, self.namespace)

    def test_finished_client_rebuilds_the_profile_before_reconnecting(self):
        calls = Mock()
        calls.attach_mock(self.manager.UnregisterProfile, 'unregister')
        calls.attach_mock(self.manager.RegisterProfile, 'register')
        calls.attach_mock(self.device.ConnectProfile, 'connect')
        self.namespace['connect']()
        self.assertEqual([call[0] for call in calls.mock_calls], ['unregister', 'register', 'connect'])
        self.manager.UnregisterProfile.assert_called_once_with(module.PROFILE_PATH + '_client', timeout=3)
        self.manager.RegisterProfile.assert_called_once_with(module.PROFILE_PATH + '_client',
            module.ACCESSORY_UUID, {'Role': 'client', 'RequireAuthentication': True}, timeout=3)
        self.namespace['retire_worker'].assert_called_once_with(self.worker)
        self.assertNotIn(self.target, self.namespace['workers'])

    def test_active_media_or_live_worker_keeps_the_profile(self):
        for active, alive in ((True, False), (False, True)):
            with self.subTest(active=active, alive=alive):
                self.namespace['media_active'].return_value = active
                self.thread.is_alive.return_value = alive
                self.namespace['connect']()
        self.manager.UnregisterProfile.assert_not_called()
        self.device.ConnectProfile.assert_not_called()

    def test_disconnected_bluetooth_keeps_the_profile(self):
        self.device.Get.return_value = False
        self.namespace['connect']()
        self.manager.UnregisterProfile.assert_not_called()
        self.device.ConnectProfile.assert_not_called()

    def test_another_live_worker_defers_the_client_profile_rebuild(self):
        other_thread = Mock()
        other_thread.is_alive.return_value = True
        self.namespace['workers']['/org/bluez/hci1/other'] = (Mock(), other_thread, Mock())
        self.namespace['connect']()
        self.manager.UnregisterProfile.assert_not_called()
        self.device.ConnectProfile.assert_not_called()
        self.assertIn(self.target, self.namespace['workers'])

    def test_server_channel_retirement_preserves_the_client_profile(self):
        self.thread.name = 'RFCOMM-server'
        self.namespace['connect']()
        self.namespace['retire_worker'].assert_called_once_with(self.worker)
        self.manager.UnregisterProfile.assert_not_called()
        self.device.ConnectProfile.assert_called_once()

    def test_partial_profile_rebuild_failure_relaunches_the_backend(self):
        self.manager.RegisterProfile.side_effect = self.error('fixture failure')
        self.namespace['connect']()
        self.namespace['loop'].quit.assert_called_once()
        self.device.ConnectProfile.assert_not_called()
        self.assertFalse(self.namespace['connecting'][0])


class ProbeTests(unittest.TestCase):
    def test_retiring_stale_channel_unblocks_reader_and_allows_replacement(self):
        phone, car = socket.socketpair()
        stop = threading.Event()
        finished = threading.Event()
        def reader():
            try:
                phone.recv(1)
            finally:
                phone.close()
                finished.set()
        worker = threading.Thread(target=reader)
        worker.start()
        try:
            module.retire_worker((stop, worker, phone))
            self.assertTrue(stop.is_set())
            self.assertTrue(finished.is_set())
            self.assertFalse(worker.is_alive())
        finally:
            car.close()

    def test_active_media_lock_prevents_unnecessary_bluetooth_reconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'media.lock')
            self.assertFalse(module.media_active(path))
            with open(path, 'w') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertTrue(module.media_active(path))
                fcntl.flock(owner, fcntl.LOCK_UN)
                self.assertFalse(module.media_active(path))

    def test_phone_sdp_discoverable_by_both_iap_service_ids(self):
        root = ET.fromstring(module.service_record(19))
        classes = root.find("attribute[@id='0x0001']/sequence")
        self.assertEqual([element.attrib['value'] for element in classes],
                         [module.PHONE_UUID, module.IAP_V2_UUID])
        protocols = root.find("attribute[@id='0x0004']/sequence")
        self.assertEqual(protocols[1][1].attrib['value'], '19')
        with self.assertRaises(ValueError):
            module.service_record(0)

    def test_phone_handshake_and_certificate_probe(self):
        phone, car = socket.socketpair()
        stop = threading.Event()
        worker = threading.Thread(target=module.probe, args=(phone, stop, 10))
        decoder = Decoder()
        queue = []
        car.settimeout(2)
        worker.start()

        def receive():
            while not queue:
                queue.extend(decoder.feed(car.recv(4096)))
            return queue.pop(0)

        try:
            # A phone must not initiate accessory DETECT.
            car.settimeout(0.25)
            with self.assertRaises(socket.timeout):
                car.recv(4096)
            car.settimeout(2)
            car.sendall(DETECT)
            self.assertEqual(receive(), DETECT)
            car.sendall(encode(Packet(SYN, 0x20, 0, 0, synchronization())))
            syn = receive()
            self.assertEqual((syn.control, syn.acknowledgement), (SYN | ACK, 0x20))
            car.sendall(encode(Packet(ACK, 0x20, syn.sequence, 0, None)))
            ident = receive()
            self.assertEqual(ident.payload, Frame(0x1d00, b'').encoded())
            # Dropped ACK triggers retransmit with the same sequence and body.
            self.assertEqual(receive(), ident)
            car.sendall(encode(Packet(ACK, 0x21, ident.sequence, 10,
                                      Frame(0x1d01, b'').encoded())))
            ack = receive()
            self.assertEqual(ack.acknowledgement, 0x21)
            # ACK-only packets carry the last sequence number sent, not 0.
            self.assertEqual(ack.sequence, ident.sequence)
            accepted = receive()
            self.assertEqual(accepted.payload, Frame(0x1d02, b'').encoded())
            car.sendall(encode(Packet(ACK, 0x21, accepted.sequence, 0, None)))
            cert_request = receive()
            self.assertEqual(cert_request.payload, Frame(0xaa00, b'').encoded())
            car.sendall(encode(Packet(ACK, 0x22, cert_request.sequence, 10,
                                      Frame(0xaa01, encode_param(0, b'public-certificate')).encoded())))
            self.assertEqual(receive().acknowledgement, 0x22)
            # Diagnostic stops before claiming authentication success.
            car.settimeout(0.3)
            with self.assertRaises(socket.timeout):
                car.recv(4096)
        finally:
            stop.set()
            worker.join(2)
            car.close()
        self.assertFalse(worker.is_alive())


class IdentificationParsingTests(unittest.TestCase):
    def test_ea_protocols_from_identification(self):
        group = lambda ident, name: encode_param(10, encode_param(0, bytes([ident])) +
                                                 encode_param(1, name + b'\x00'))
        frame = Frame(0x1d01, encode_param(0, b'Honda CIVIC\x00') +
                      group(1, b'com.honda.cp.allhonda') + group(3, b'com.honda.hondalink.hlc') +
                      encode_param(10, b'\x00'))
        self.assertEqual(module.parse_ea_protocols(frame),
                         [(1, 'com.honda.cp.allhonda'), (3, 'com.honda.hondalink.hlc')])

    def test_bluetooth_component_ids(self):
        frame = Frame(0x4e03, encode_param(0, b'\x00\x01') + encode_param(0, b'\x01') +
                      encode_param(0, b'\x00\x05'))
        self.assertEqual(module.parse_component_ids(frame), [1, 5])


if __name__ == '__main__':
    unittest.main()
