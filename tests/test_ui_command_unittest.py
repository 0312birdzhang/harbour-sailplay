import os
import plistlib
import tempfile
import threading
import unittest
from carplay_proto.videodemo import UiCommands, ScreenFeedback


class UiCommandTests(unittest.TestCase):
    def test_hu_request_ui_reclaims_screen_and_audio(self):
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
        self.assertEqual(modes['resources'][1]['entity'], 1)
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

    def test_mode_fm_then_request_ui_restores_both_resources_and_audio_gain(self):
        import time
        from types import SimpleNamespace
        from unittest.mock import Mock
        modes={'appStates':[],'resources':[{'resourceID':i,'entity':1,'permanentEntity':1} for i in (1,2)]}
        changed=threading.Event();resume=threading.Event();audio=SimpleNamespace(gain=1.0);screen=Mock();payloads=[]
        class Client:
            def request(self,method,path,body=b'',headers=None):
                if body:payloads.append(plistlib.loads(body))
                return 200,{},b''
        feedback=ScreenFeedback(Client(),modes=modes,resume=resume,screen=screen,resource_changed=changed,audio=audio)
        def wait_for(predicate):
            end=time.monotonic()+2
            while not predicate() and time.monotonic()<end:time.sleep(.01)
            self.assertTrue(predicate())
        try:
            for resource in modes['resources']:resource.update(entity=2,permanentEntity=2)
            changed.set();wait_for(lambda:audio.gain==0 and screen.ownership.call_args is not None
                                  and screen.ownership.call_args.args==(2,))
            screen.ownership.assert_called_with(2)
            resume.set();wait_for(lambda:audio.gain==1 and screen.ownership.call_args is not None
                                 and screen.ownership.call_args.args==(1,))
            self.assertTrue(all(r['entity']==1 and r['permanentEntity']==1 for r in modes['resources']))
            screen.ownership.assert_called_with(1)
            self.assertEqual([r['entity'] for r in payloads[-1]['params']['resources']],[1,1])
        finally:feedback.close()
    def test_denied_reentry_does_not_unmute_or_claim_screen(self):
        import time
        from types import SimpleNamespace
        from unittest.mock import Mock
        modes={'resources':[{'resourceID':i,'entity':2,'permanentEntity':2} for i in (1,2)]}
        resume=threading.Event();called=threading.Event();audio=SimpleNamespace(gain=0);screen=Mock()
        class Client:
            def request(self,*a,**k):called.set();return 422,{},b''
        feedback=ScreenFeedback(Client(),modes=modes,resume=resume,screen=screen,audio=audio)
        try:
            resume.set();self.assertTrue(called.wait(1));time.sleep(.05)
            self.assertTrue(all(r['entity']==2 for r in modes['resources']))
            self.assertEqual(audio.gain,0);screen.ownership.assert_not_called()
        finally:feedback.close()
    def test_new_resource_event_during_reentry_is_not_overwritten(self):
        import time
        from types import SimpleNamespace
        modes={'resources':[{'resourceID':i,'entity':2,'permanentEntity':2} for i in (1,2)]}
        resume=threading.Event();dirty=threading.Event();revision=[0];audio=SimpleNamespace(gain=0);seen=threading.Event()
        class Client:
            first=True
            def request(self,*a,**k):
                if self.first:
                    self.first=False;revision[0]+=1;dirty.set();seen.set()
                return 200,{},b''
        feedback=ScreenFeedback(Client(),modes=modes,resume=resume,resource_changed=dirty,audio=audio,mode_revision=revision)
        try:
            resume.set();self.assertTrue(seen.wait(1));time.sleep(.3)
            self.assertEqual(audio.gain,0)
            self.assertTrue(all(r['entity']==2 for r in modes['resources']))
        finally:feedback.close()
