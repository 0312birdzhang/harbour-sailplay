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
        self.teardown_status = 200
        self.port = port

    def request(self, method, path, body=b'', headers=None):
        payload = plistlib.loads(body)
        self.requests.append((method, payload))
        if method == 'SETUP':
            stream = payload['streams'][0]
            reply = {'streams': [{'type': stream['type'], 'dataPort': self.port,
                                  'streamConnectionID': stream['streamConnectionID']}]}
            return self.setup_status, {}, plistlib.dumps(reply, fmt=plistlib.FMT_BINARY)
        return self.teardown_status, {}, b''


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

    def test_setup_refused_after_teardown_stops_sending_and_a_retry_skips_teardown(self):
        client = FakeClient(setup_status=455, port=6004)
        sender = self.sender(client)
        old_id = sender.stream_id
        self.assertFalse(sender.torn_down)
        self.assertFalse(sender.reopen(client, ('127.0.0.1', 7000)))
        # The receiver accepted TEARDOWN: its stream is gone whatever we keep.
        self.assertTrue(sender.torn_down)
        self.assertEqual([method for method, _ in client.requests], ['TEARDOWN', 'SETUP'])
        client.setup_status = 200
        self.assertTrue(sender.reopen(client, ('127.0.0.1', 7000)))
        self.assertEqual([method for method, _ in client.requests], ['TEARDOWN', 'SETUP', 'SETUP'])
        self.assertFalse(sender.torn_down)
        self.assertNotEqual(sender.stream_id, old_id)
        self.assertEqual(sender.sock.getpeername(), ('127.0.0.1', 6004))

    def test_refused_teardown_leaves_the_old_stream_in_use(self):
        client = FakeClient(setup_status=455)
        client.teardown_status = 455
        sender = self.sender(client)
        old_id, old_sock = sender.stream_id, sender.sock
        self.assertFalse(sender.reopen(client, ('127.0.0.1', 7000)))
        self.assertFalse(sender.torn_down)
        self.assertEqual(sender.stream_id, old_id)
        self.assertIs(sender.sock, old_sock)


if __name__ == '__main__':
    unittest.main()
