"""iAP2 tunnelled through AirPlay iAPSendMessage, end to end with a mock head unit."""
import base64
import hashlib
import importlib.util
import json
import os
import plistlib
import queue
import tempfile
import threading
import time
import unittest
from unittest import mock

from carplay_proto.iap2link import ACK, DETECT, SYN, Decoder, Packet, encode, synchronization
from carplay_proto.iaptunnel import IAPTunnel, tunnel_payload
from carplay_proto.wire import Frame, Framer, encode_param

path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'wireless-probe.py')
spec = importlib.util.spec_from_file_location('wireless_probe_tunnel', path)
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils
except ImportError:  # the phone has no python cryptography
    rsa = None


class TunnelPayloadTests(unittest.TestCase):
    def test_payload_extraction(self):
        self.assertEqual(tunnel_payload({'type': 'iAPSendMessage', 'params': {'data': DETECT}}), DETECT)
        self.assertIsNone(tunnel_payload({'type': 'iAPSendMessage', 'params': {}}))
        self.assertIsNone(tunnel_payload({'type': 'iAPSendMessage', 'params': {'data': b''}}))
        self.assertIsNone(tunnel_payload({'type': 'iAPSendMessage'}))

    def test_head_unit_detect_message_size_matches_capture(self):
        # The Honda's iAPSendMessage events were 94-byte plists.
        body = plistlib.dumps({'type': 'iAPSendMessage', 'params': {'data': DETECT}},
                              fmt=plistlib.FMT_BINARY)
        self.assertEqual(len(body), 94)

    def test_link_restarts_after_it_ends_and_respects_limit(self):
        runs = []

        def run_link(sock, stop):
            runs.append(sock.recv(16))

        sent = queue.Queue()
        tunnel = IAPTunnel(run_link, sent.put, max_starts=2)
        try:
            for _ in range(4):
                tunnel.feed(b'x')
                time.sleep(0.05)
            self.assertEqual(runs, [b'x', b'x'])
            self.assertFalse(tunnel.feed(b'x'))
        finally:
            tunnel.close()


class SendTests(unittest.TestCase):
    def test_send_iap_posts_command(self):
        from carplay_proto.videodemo import send_iap
        requests = []

        class Client:
            def request(self, method, path, body=b'', headers=None):
                requests.append((method, path, body))
                return 200, {}, b''

        send_iap(Client(), DETECT)
        method, path, body = requests[0]
        self.assertEqual((method, path), ('POST', '/command'))
        self.assertEqual(plistlib.loads(body), {'type': 'iAPSendMessage', 'params': {'data': DETECT}})

    def test_send_failure_is_reported_not_raised(self):
        from carplay_proto.videodemo import send_iap

        class Client:
            def request(self, *args, **kwargs):
                raise EOFError('RTSP peer closed')

        send_iap(Client(), DETECT)

    def test_requests_from_threads_do_not_interleave(self):
        from carplay_proto.rtspclient import RTSPClient
        client = RTSPClient(None)
        active, overlaps = [0], []

        def fake(method, path, body=b'', headers=None):
            active[0] += 1
            overlaps.append(active[0])
            time.sleep(0.01)
            active[0] -= 1
            return 200, {}, b''

        client._request = fake
        workers = [threading.Thread(target=client.request, args=('POST', '/command')) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(max(overlaps), 1)


class NotificationTests(unittest.TestCase):
    def test_only_messages_the_accessory_receives(self):
        frames = probe_module.device_notifications('Phone', 'AA:BB:CC:DD:EE:FF', {0x4e09, 0x4e0d})
        self.assertEqual([f.message_id for f in frames], [0x4e09, 0x4e0d])
        self.assertEqual(frames[0].parameters()[0].payload, b'Phone\x00')

    def test_tunnel_thread_lines_are_prefixed(self):
        import io, logging, sys
        from carplay_proto.runtime_logging import log_to_stdout
        stream, saved = io.StringIO(), sys.stdout
        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        try:
            sys.stdout = stream
            log_to_stdout()
            logging.info('main')
            worker = threading.Thread(target=logging.info, args=('link',), name='iAP tunnel link 1')
            worker.start()
            worker.join()
        finally:
            sys.stdout = saved
            for handler in list(root.handlers):
                root.removeHandler(handler)
            for handler in handlers:
                root.addHandler(handler)
            root.setLevel(level)
        self.assertEqual(stream.getvalue(), 'main\niAP tunnel: link\n')


@unittest.skipIf(rsa is None, 'needs python cryptography')
class AirPlayLinkTests(unittest.TestCase):
    def test_full_handshake_over_tunnel_without_wifi_request(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        certificate = b'honda-certificate'
        with tempfile.TemporaryDirectory() as directory:
            der = key.public_key().public_bytes(serialization.Encoding.DER,
                                                serialization.PublicFormat.SubjectPublicKeyInfo)
            with open(os.path.join(directory, 'dev_74_D7_CA_65_F7_1B.json'), 'w') as pin:
                json.dump({'algorithm': 'rsa-pkcs1-sha1',
                           'certificate_sha256': hashlib.sha256(certificate).hexdigest(),
                           'public_key_der': base64.b64encode(der).decode()}, pin)
            to_car = queue.Queue()
            decoder, framer, pending = Decoder(), Framer(), []

            def receive():
                while not pending:
                    pending.extend(decoder.feed(to_car.get(timeout=3)))
                return pending.pop(0)

            def frame_of(packet):
                return list(framer.offer(packet.payload))[0]

            with mock.patch.object(probe_module, 'previous_head_unit',
                                   return_value='/org/bluez/hci0/dev_74_D7_CA_65_F7_1B'):
                tunnel = IAPTunnel(lambda sock, stop: probe_module.airplay_link(
                    sock, stop, 'Galaxy Note 10+', 'AA:BB:CC:DD:EE:FF',
                    accessory_directory=directory), to_car.put)
                try:
                    tunnel.feed(DETECT)
                    self.assertEqual(receive(), DETECT)
                    tunnel.feed(encode(Packet(SYN, 0x40, 0, 0, synchronization())))
                    syn = receive()
                    self.assertEqual((syn.control, syn.acknowledgement), (SYN | ACK, 0x40))
                    tunnel.feed(encode(Packet(ACK, 0x40, syn.sequence, 0, None)))
                    ident = receive()
                    self.assertEqual(frame_of(ident).message_id, 0x1d00)
                    tunnel.feed(encode(Packet(ACK, 0x41, ident.sequence, 10,
                                              Frame(0x1d01, b'').encoded())))
                    self.assertEqual(receive().acknowledgement, 0x41)
                    accepted = receive()
                    self.assertEqual(frame_of(accepted).message_id, 0x1d02)
                    tunnel.feed(encode(Packet(ACK, 0x41, accepted.sequence, 0, None)))
                    cert_request = receive()
                    self.assertEqual(frame_of(cert_request).message_id, 0xaa00)
                    tunnel.feed(encode(Packet(ACK, 0x42, cert_request.sequence, 10,
                                              Frame(0xaa01, encode_param(0, certificate)).encoded())))
                    self.assertEqual(receive().acknowledgement, 0x42)
                    challenge_packet = receive()
                    challenge = frame_of(challenge_packet)
                    self.assertEqual(challenge.message_id, 0xaa02)
                    nonce = challenge.parameters()[0].payload
                    signature = key.sign(nonce, padding.PKCS1v15(), utils.Prehashed(hashes.SHA1()))
                    tunnel.feed(encode(Packet(ACK, 0x43, challenge_packet.sequence, 10,
                                              Frame(0xaa03, encode_param(0, signature)).encoded())))
                    self.assertEqual(receive().acknowledgement, 0x43)
                    succeeded = receive()
                    self.assertEqual(frame_of(succeeded).message_id, 0xaa05)
                    tunnel.feed(encode(Packet(ACK, 0x43, succeeded.sequence, 0, None)))
                    # Then the device updates an iPhone sends, in order...
                    notified = []
                    for _ in range(4):
                        packet = receive()
                        frame = frame_of(packet)
                        notified.append(frame.message_id)
                        tunnel.feed(encode(Packet(ACK, 0x43, packet.sequence, 0, None)))
                    self.assertEqual(notified, [0x4e0c, 0x4e09, 0x4e0e, 0x4e0d])
                    # ...and no Wi-Fi configuration request: Wi-Fi is already up.
                    with self.assertRaises(queue.Empty):
                        to_car.get(timeout=1.2)
                    # A DETECT on the established link means the head unit
                    # restarted: that link ends and the next DETECT is answered.
                    tunnel.feed(DETECT)
                    time.sleep(0.3)
                    tunnel.feed(DETECT)
                    self.assertEqual(to_car.get(timeout=3), DETECT)
                    self.assertEqual(tunnel.starts, 2)
                finally:
                    tunnel.close()


if __name__ == '__main__':
    unittest.main()
