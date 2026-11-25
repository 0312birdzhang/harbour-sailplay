"""Exercise the executable against a mock accessory, including retransmission."""
import importlib.util
import os
import socket
import struct
import threading
import unittest
import tempfile
import fcntl
import xml.etree.ElementTree as ET

from carplay_proto.iap2link import ACK, DETECT, SYN, Decoder, Packet, encode, synchronization
from carplay_proto.wire import Frame, encode_param

path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'wireless-probe.py')
spec = importlib.util.spec_from_file_location('wireless_probe', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProbeTests(unittest.TestCase):
    def test_only_a_new_bluetoothd_asks_for_a_rebuild(self):
        self.assertTrue(module.bluez_restarted('org.bluez', ':1.3658'))
        self.assertFalse(module.bluez_restarted('org.bluez', ''))
        self.assertFalse(module.bluez_restarted('org.ofono', ':1.12'))

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

    def test_media_is_established_only_once_the_lease_holder_has_streamed(self):
        from carplay_proto.session import SessionLease
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'media.lock')
            self.assertFalse(module.media_established(path))
            lease = SessionLease('carplay', lock_path=path, status_path=None)
            lease.acquire()
            try:
                # Held from worker start-up: active, but nothing has succeeded yet.
                self.assertTrue(module.media_active(path))
                self.assertFalse(module.media_established(path))
                lease.phase('projecting')
                self.assertFalse(module.media_established(path))
                lease.streaming()
                self.assertTrue(module.media_established(path))
            finally:
                lease.close()
            # The record of a finished worker is not a running success.
            self.assertFalse(module.media_established(path))
            again = SessionLease('carplay', lock_path=path, status_path=None)
            again.acquire()
            try:
                self.assertFalse(module.media_established(path))
            finally:
                again.close()

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


class UnsupportedAccessoryTests(unittest.TestCase):
    def identify(self, body):
        """Run the probe against an accessory that identifies with body."""
        phone, accessory = socket.socketpair()
        stop = threading.Event()
        unsupported = []
        worker = threading.Thread(target=module.probe, args=(phone, stop, 10), kwargs={
            'bluetooth_device': '/org/bluez/hci0/dev_fixture', 'on_unsupported': lambda: unsupported.append(True)})
        decoder = Decoder()
        queue = []
        accessory.settimeout(2)
        worker.start()

        def receive():
            while not queue:
                queue.extend(decoder.feed(accessory.recv(4096)))
            return queue.pop(0)

        after = []
        try:
            accessory.sendall(DETECT)
            self.assertEqual(receive(), DETECT)
            accessory.sendall(encode(Packet(SYN, 0x20, 0, 0, synchronization())))
            syn = receive()
            accessory.sendall(encode(Packet(ACK, 0x20, syn.sequence, 0, None)))
            ident = receive()
            self.assertEqual(ident.payload, Frame(0x1d00, b'').encoded())
            accessory.sendall(encode(Packet(ACK, 0x21, ident.sequence, 10, Frame(0x1d01, body).encoded())))
            accessory.settimeout(0.5)
            try:
                while True:
                    data = accessory.recv(4096)
                    if not data:
                        break
                    after.extend(decoder.feed(data))
            except (socket.timeout, OSError):
                pass
        finally:
            worker.join(1)
            ended = not worker.is_alive()
            stop.set()
            worker.join(2)
            accessory.close()
        return unsupported, ended, [packet.payload for packet in after if packet.payload]

    @staticmethod
    def lists(sent, received):
        pack = lambda ids: struct.pack('>' + 'H' * len(ids), *ids)
        return encode_param(6, pack(sent)) + encode_param(7, pack(received))

    def test_earbuds_identification_ends_the_probe_and_reports_the_device(self):
        unsupported, ended, replies = self.identify(self.lists([0xea03], [0xea00, 0xea01]))
        self.assertEqual(unsupported, [True])
        self.assertTrue(ended)
        self.assertNotIn(Frame(0x1d02, b'').encoded(), replies)

    def test_head_unit_identification_is_accepted(self):
        unsupported, _, replies = self.identify(self.lists([0x5703], [0x5702, 0x4e0d]))
        self.assertEqual(unsupported, [])
        self.assertIn(Frame(0x1d02, b'').encoded(), replies)


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
