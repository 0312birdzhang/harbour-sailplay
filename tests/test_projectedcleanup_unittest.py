import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch
from carplay_proto.display import projected_apps, stop_projected_apps, DisplayPipeline

class ProjectedCleanupTests(unittest.TestCase):
    def test_only_marked_virtual_clients_are_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            for pid, display, key, state in ((101,'imira-comp-0','map','S'),
                    (102,'../../display/wayland-0','map','S'),
                    (103,'imira-comp-0','','S'),
                    (104,'imira-comp-0','sailplay-input-method','S'),
                    (105,'imira-comp-0','map','Z')):
                p=Path(tmp)/str(pid);p.mkdir()
                (p/'environ').write_bytes(('WAYLAND_DISPLAY='+display+'\0CARLIFE_APP_KEY='+key+'\0').encode())
                (p/'stat').write_text(str(pid)+' (app with spaces) '+state+' '+' '.join(['0']*18+['12345']))
            self.assertEqual(projected_apps(tmp),{101:'12345'})
    def test_pid_reuse_is_not_signalled(self):
        with patch('carplay_proto.display.projected_apps',side_effect=[{101:'old'},{101:'new'},{101:'new'}]), patch('os.kill') as kill:
            stop_projected_apps(grace=0)
            kill.assert_not_called()
    def test_stubborn_owned_client_is_force_stopped(self):
        with patch('carplay_proto.display.projected_apps',return_value={101:'same'}), patch('os.kill') as kill:
            stop_projected_apps(grace=0)
            self.assertEqual(kill.call_args_list[0].args,(101,signal.SIGTERM))
            self.assertEqual(kill.call_args_list[1].args,(101,signal.SIGKILL))
    def test_unstarted_pipeline_cannot_clean_another_session(self):
        with patch('carplay_proto.display.stop_projected_apps') as stop, patch('time.sleep'):
            p=DisplayPipeline();p.close();p.close()
            stop.assert_not_called()
