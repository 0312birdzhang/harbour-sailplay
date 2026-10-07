"""Exercise the executable against a mock accessory, including retransmission."""
import importlib.util
import os
import socket
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
            self.assertEqual(receive().acknowledgement, 0x21)
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


if __name__ == '__main__':
    unittest.main()
