"""Keyframe requests on kernels without /proc/PID/task/PID/children."""
import os
import plistlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from carplay_proto.display import child_pids
from carplay_proto.screenstream import ScreenStream


def fake_proc(root, processes, children_files=None):
    for pid, (ppid, comm) in processes.items():
        os.makedirs(os.path.join(root, str(pid), 'task', str(pid)))
        with open(os.path.join(root, str(pid), 'stat'), 'w') as stat:
            stat.write('{} ({}) S {} 1 1 0 -1\n'.format(pid, comm, ppid))
    for pid, children in (children_files or {}).items():
        with open(os.path.join(root, str(pid), 'task', str(pid), 'children'), 'w') as source:
            source.write(' '.join(map(str, children)) + ' ')
    os.makedirs(os.path.join(root, 'self'))


class ChildPidTests(unittest.TestCase):
    def test_scan_without_children_file(self):
        with tempfile.TemporaryDirectory() as root:
            # Command names can contain spaces and parentheses.
            fake_proc(root, {100: (1, 'su'), 101: (100, 'carlife-capture'),
                             102: (100, 'odd ) name'), 103: (1, 'other'), 104: (101, 'grandchild')})
            self.assertEqual(child_pids(100, proc=root), [101, 102])

    def test_children_file_is_used_when_present(self):
        with tempfile.TemporaryDirectory() as root:
            fake_proc(root, {100: (1, 'su'), 101: (100, 'x')}, children_files={100: [555]})
            self.assertEqual(child_pids(100, proc=root), [555])


class ResumeKeyframeTests(unittest.TestCase):
    def test_failed_keyframe_request_does_not_end_resume(self):
        class Video:
            def shutdown(self, how): pass
            def close(self): pass
            def sendall(self, payload): pass

        class Client:
            def request(self, method, path, body=None, headers=None):
                if method == 'SETUP':
                    return 200, {}, plistlib.dumps({'streams': [{'type': 110, 'dataPort': 1234}]})
                return 200, {}, b''

        def failing():
            raise RuntimeError('capture process exited before keyframe request')

        stream = ScreenStream(Client(), '127.0.0.1', 'wlan0', bytes(32), {'uuid': 'screen'}, Video(), 42,
                              request_keyframe=failing)
        try:
            stream.ownership(2)
            with patch('carplay_proto.screenstream.connect', return_value=SimpleNamespace(sock=Video())):
                stream.ownership(1)
            self.assertEqual(stream.desired_owner, 1)
            self.assertTrue(stream.send(b'config', [b'\x65\x80'], 0))
        finally:
            stream.close()


if __name__ == '__main__':
    unittest.main()
