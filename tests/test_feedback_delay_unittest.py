import socket
import unittest
from unittest.mock import Mock
from carplay_proto.rtspclient import RTSPClient
class FeedbackDelayTests(unittest.TestCase):
    def test_late_response_keeps_same_cseq_and_sends_only_once(self):
        sock=Mock();sock.recv.side_effect=[socket.timeout(),b'RTSP/1.0 200 OK\r\nCSeq: 1\r\nContent-Length: 0\r\n\r\n']
        client=RTSPClient(sock)
        self.assertEqual(client.request('POST','/feedback')[0],200)
        sock.sendall.assert_called_once()
        self.assertEqual(client.sequence,1)
    def test_other_request_timeout_is_still_fatal(self):
        sock=Mock();sock.recv.side_effect=socket.timeout()
        with self.assertRaises(socket.timeout):RTSPClient(sock).request('SETUP','/')
