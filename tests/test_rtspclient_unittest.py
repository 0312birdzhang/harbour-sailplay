import unittest
from carplay_proto.rtspclient import RTSPClient, EncryptedSocket
from carplay_proto.controlcipher import ControlCipher


class Socket:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
    def sendall(self, data):
        self.sent = data
    def recv(self, size):
        return next(self.chunks, b'')


class RTSPTests(unittest.TestCase):
    def test_encrypted_fragments_and_buffered_plaintext(self):
        key = bytes(range(32))
        plaintext = b'x' * 17000
        encrypted = ControlCipher(key,key).encrypt(plaintext)
        wire = Socket([encrypted[1:90], encrypted[90:]])
        sock = EncryptedSocket(wire, ControlCipher(key,key), encrypted[:1])
        recovered = b''
        while len(recovered) < len(plaintext):
            recovered += sock.recv(500)
        self.assertEqual(recovered, plaintext)
        sock.sendall(b'hello')
        self.assertEqual(ControlCipher(key,key).decrypt(wire.sent).data,b'hello')
    def test_fragmented_response_and_remaining_bytes(self):
        sock = Socket([b'RTSP/1.0 200 OK\r\nCSeq: 1\r\nContent-Len', b'gth: 3\r\n\r\na', b'bcNEXT'])
        client = RTSPClient(sock)
        self.assertEqual(client.request('GET', '/info')[2], b'abc')
        self.assertEqual(client.buffer, b'NEXT')
    def test_limits_and_sequence(self):
        for response in (b'CSeq: 2\r\nContent-Length: 0', b'CSeq: 1\r\nContent-Length: 4194305'):
            client = RTSPClient(Socket([b'RTSP/1.0 200 OK\r\n' + response + b'\r\n\r\n']))
            with self.assertRaises(ValueError):
                client.request('GET', '/info')
