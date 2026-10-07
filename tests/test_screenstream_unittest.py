import plistlib
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from carplay_proto.screenstream import ScreenStream


class ScreenStreamTests(unittest.TestCase):
    def test_screen_only_teardown_order_and_resume_from_keyframe(self):
        order = []
        class Video:
            def shutdown(self, how): order.append('shutdown')
            def close(self): order.append('close')
            def sendall(self, payload): order.append('packet')
        class Client:
            def request(self, method, path, body=None, headers=None):
                order.append(method)
                if body:
                    payload = plistlib.loads(body)
                    self.last_payload = payload
                    assert [s['type'] for s in payload['streams']] == [110]
                if method == 'SETUP':
                    return 200, {}, plistlib.dumps({'streams': [{'type': 110, 'dataPort': 1234}]})
                return 200, {}, b''
        client = Client()
        stream = ScreenStream(client, '127.0.0.1', 'wlan0', bytes(32), {'uuid': 'screen'}, Video(), 42)
        try:
            stream.ownership(2)
            self.assertEqual(order, ['shutdown', 'close', 'TEARDOWN'])
            self.assertEqual(client.last_payload, {'streams': [{'type': 110, 'uuid': 'screen'}]})
            self.assertFalse(stream.send(b'config', [b'\x65\x80'], 0))
            with patch('carplay_proto.screenstream.connect', return_value=SimpleNamespace(sock=Video())):
                stream.ownership(1)
            self.assertEqual(order[-2:], ['SETUP', 'RECORD'])
            self.assertFalse(stream.send(b'config', [b'\x41\x80'], 0))
            self.assertTrue(stream.send(b'config', [b'\x65\x80'], 0))
            self.assertFalse(stream.need_idr)
            self.assertEqual(order[-2:], ['packet', 'packet'])
            # Reclaiming an already active screen does not create a second stream.
            previous = list(order)
            stream.ownership(1)
            self.assertEqual(order, previous)
        finally:
            stream.close()
