import socket
import tempfile
import os
import unittest
from unittest.mock import patch
from carplay_proto.touch import TouchInput

class TouchPrivateChannelTests(unittest.TestCase):
    def test_absolute_gesture_reaches_only_private_socket(self):
        with tempfile.TemporaryDirectory() as d:
            server=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);path=d+'/touch'
            server.bind(path);server.settimeout(1)
            t=TouchInput.__new__(TouchInput)
            t.width,t.height=1920,720;t.debug_reports=5;t.layouts={'screen':{}}
            t.sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);t.path=path
            t.x,t.y,t.down=960,360,False
            value={'type':'hidSendReport','uuid':'screen','hidReport':b''}
            try:
                with patch('carplay_proto.touch.decode_touch',side_effect=[(True,70,650),(True,80,640),(False,80,640)]),patch('carplay_proto.touch.os.write') as write:
                    for _ in range(3):t.command(value)
                    write.assert_not_called()
                self.assertEqual([server.recv(64) for _ in range(3)],[b'T 1 70 650',b'T 1 80 640',b'T 0 80 640'])
            finally:t.close();server.close()
    def test_missing_compositor_never_falls_back_to_global_input(self):
        t=TouchInput.__new__(TouchInput);t.sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        t.path='/nonexistent-sailplay-input/socket';t.down=True;t.x=0;t.y=0
        with patch('carplay_proto.touch.os.open') as opened,patch('carplay_proto.touch.os.write') as write:
            with self.assertRaises(OSError):t.send(True,1,2)
            t.close();opened.assert_not_called();write.assert_not_called()
