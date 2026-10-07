import os
import plistlib
import tempfile
import threading
import unittest
from carplay_proto.videodemo import UiCommands, ScreenFeedback


class UiCommandTests(unittest.TestCase):
    def test_hu_request_ui_reclaims_screen_without_changing_audio(self):
        resume = threading.Event()
        called = threading.Event()
        modes = {'appStates': [], 'resources': [
            {'resourceID': 1, 'entity': 2, 'permanentEntity': 2},
            {'resourceID': 2, 'entity': 2, 'permanentEntity': 2}]}
        class Client:
            def request(self, method, path, body, headers):
                self.payload = plistlib.loads(body)
                called.set()
                return 200, {}, b''
        client = Client()
        feedback = ScreenFeedback(client, modes=modes, resume=resume)
        try:
            resume.set()
            self.assertTrue(called.wait(1))
        finally:
            feedback.close()
        self.assertEqual(modes['resources'][0]['entity'], 1)
        self.assertEqual(modes['resources'][1]['entity'], 2)
        self.assertFalse(resume.is_set())

    def test_return_changes_screen_only_and_handles_rejection(self):
        for response in (200, 422):
            with tempfile.TemporaryDirectory() as directory:
                commands = UiCommands(os.path.join(directory, 'commands'))
                modes = {'appStates': [], 'resources': [
                    {'resourceID': 1, 'entity': 1, 'permanentEntity': 1},
                    {'resourceID': 2, 'entity': 1, 'permanentEntity': 1}]}
                called = threading.Event()
                class Client:
                    def request(self, method, path, body, headers):
                        self.payload = plistlib.loads(body)
                        called.set()
                        return response, {}, b''
                client = Client()
                feedback = ScreenFeedback(client, commands, modes)
                try:
                    os.write(commands.writer, b'unrecognized\nreturn-')
                    self.assertFalse(commands.return_requested())
                    os.write(commands.writer, b'car\n')
                    self.assertTrue(called.wait(1))
                finally:
                    feedback.close()
                    commands.close()
                self.assertEqual(client.payload['type'], 'modesChanged')
                resources = client.payload['params']['resources']
                self.assertEqual(resources[0]['entity'], 2)
                self.assertEqual(resources[1]['entity'], 1)
                self.assertEqual(modes['resources'][0]['entity'], 2 if response == 200 else 1)
                self.assertFalse(os.path.exists(commands.path))

    def test_rejects_existing_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'commands')
            with open(path, 'w') as output:
                output.write('preserve')
            with self.assertRaises(RuntimeError):
                UiCommands(path)
            with open(path) as source:
                self.assertEqual(source.read(), 'preserve')
