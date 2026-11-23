import plistlib
import socket
import unittest

from carplay_proto.audio import AudioSender


class FakeTransport:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', 0))


class FakeClient:
    def __init__(self, setup_status=200, port=6000):
        self.sock = FakeTransport()
        self.requests = []
        self.setup_status = setup_status
        self.port = port

    def request(self, method, path, body=b'', headers=None):
        payload = plistlib.loads(body)
        self.requests.append((method, payload))
        if method == 'SETUP':
            stream = payload['streams'][0]
            reply = {'streams': [{'type': stream['type'], 'dataPort': self.port,
                                  'streamConnectionID': stream['streamConnectionID']}]}
            return self.setup_status, {}, plistlib.dumps(reply, fmt=plistlib.FMT_BINARY)
        return 200, {}, b''


INFO = {'audioFormats': [{'type': 102, 'audioType': 'media', 'audioOutputFormats': 8388608}]}


class AudioReopenTest(unittest.TestCase):
    def sender(self, client):
        sender = AudioSender(client, bytes(32), INFO)
        self.addCleanup(sender.sock.close)
        self.addCleanup(sender.control.close)
        self.addCleanup(client.sock.sock.close)
        return sender

    def test_reopen_replaces_stream_socket_and_encoder(self):
        client = FakeClient(port=6002)
        sender = self.sender(client)
        old_id, old_encoder, old_sock = sender.stream_id, sender.encoder, sender.sock
        self.assertTrue(sender.reopen(client, ('127.0.0.1', 7000)))
        (teardown, torn), (setup, opened) = client.requests
        self.assertEqual((teardown, setup), ('TEARDOWN', 'SETUP'))
        self.assertEqual(torn['streams'][0], {'type': 102, 'streamConnectionID': old_id})
        self.assertEqual(opened['streams'][0]['streamConnectionID'], sender.stream_id)
        self.assertNotEqual(sender.stream_id, old_id)
        self.assertIsNot(sender.encoder, old_encoder)
        self.assertEqual(sender.encoder.timestamp, 0)
        self.assertEqual(sender.sock.getpeername(), ('127.0.0.1', 6002))
        self.assertEqual(old_sock.fileno(), -1)

    def test_rejected_setup_keeps_the_existing_stream(self):
        client = FakeClient(setup_status=455)
        sender = self.sender(client)
        old_id, old_encoder, old_sock = sender.stream_id, sender.encoder, sender.sock
        self.assertFalse(sender.reopen(client, ('127.0.0.1', 7000)))
        self.assertEqual(sender.stream_id, old_id)
        self.assertIs(sender.encoder, old_encoder)
        self.assertIs(sender.sock, old_sock)


if __name__ == '__main__':
    unittest.main()
