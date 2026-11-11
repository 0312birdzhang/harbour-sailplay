import os
from pathlib import Path
import signal
import tempfile
import unittest
from types import SimpleNamespace
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
                (p/'cmdline').write_bytes(b'/usr/bin/app\0')
                (p/'stat').write_text(str(pid)+' (app with spaces) '+state+' '+' '.join(['0']*18+['12345']))
            self.assertEqual(projected_apps(tmp),{101:'12345'})
    def test_old_projection_shell_is_owned_without_an_app_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            for pid, display, executable, entry in (
                    (101, 'imira-comp-0', '/opt/sailplay/carui/carui', '/opt/sailplay/carui/main.qml'),
                    (102, '../../display/wayland-0', '/opt/sailplay/carui/carui', '/opt/sailplay/carui/main.qml'),
                    (103, 'imira-comp-0', '/opt/sailplay/carui/carui', '/opt/sailplay/carui/mobile-s'),
                    (104, 'imira-comp-0', '/unrelated/carui', '/opt/sailplay/carui/main.qml')):
                process = Path(tmp) / str(pid)
                process.mkdir()
                (process / 'environ').write_bytes(('WAYLAND_DISPLAY=' + display + '\0').encode())
                (process / 'cmdline').write_bytes((executable + '\0' + entry + '\0').encode())
                (process / 'stat').write_text(str(pid) + ' (carui) S ' + ' '.join(['0'] * 18 + ['12345']))
            self.assertEqual(projected_apps(tmp), {101: '12345'})
    def test_pid_reuse_is_not_signalled(self):
        with patch('carplay_proto.display.projected_apps',side_effect=[{101:'old'},{101:'new'},{101:'new'}]), patch('os.kill') as kill:
            stop_projected_apps(grace=0)
            kill.assert_not_called()
    def test_workers_require_a_pipeline_marker_and_matching_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = '/tmp/sailplay-display-500.h264'
            fixtures = (
                (101, marker, ['/opt/sailplay/imira-comp', '--width', '960']),
                (102, marker, ['/opt/sailplay/carlife-capture', '--out', marker]),
                (103, marker, ['/usr/bin/python3', '/opt/sailplay/scripts/keyboard-server.py']),
                (104, '', ['/opt/sailplay/imira-comp']),
                (105, marker, ['/opt/sailplay/carlife-capture', '--out', '/unrelated']),
                (106, marker, ['/usr/bin/python3', '/unrelated/keyboard-server.py']),
                (107, '/unrelated/file', ['/opt/sailplay/imira-comp']))
            for pid, value, arguments in fixtures:
                process = Path(tmp) / str(pid)
                process.mkdir()
                (process / 'environ').write_bytes(('SAILPLAY_DISPLAY_PIPELINE=' + value + '\0').encode())
                (process / 'cmdline').write_bytes(('\0'.join(arguments) + '\0').encode())
                (process / 'stat').write_text(str(pid) + ' (worker) S ' + ' '.join(['0'] * 18 + ['12345']))
            self.assertEqual(projected_apps(tmp, workers=True), {101: '12345', 102: '12345', 103: '12345'})
    def test_private_input_method_is_cleaned_only_with_its_worker_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            for pid, marker, display in ((101, '/tmp/sailplay-display-500.h264', 'imira-comp-0'),
                                        (102, '', 'imira-comp-0'),
                                        (103, '/tmp/sailplay-display-500.h264', '../../display/wayland-0')):
                process = Path(tmp) / str(pid)
                process.mkdir()
                (process / 'environ').write_bytes(('SAILPLAY_DISPLAY_PIPELINE=' + marker
                    + '\0CARLIFE_APP_KEY=sailplay-input-method\0WAYLAND_DISPLAY=' + display + '\0').encode())
                (process / 'cmdline').write_bytes(b'maliit-server\0-override-address\0'
                    b'unix:path=/run/user/100000/sailplay-maliit/socket\0')
                (process / 'stat').write_text(str(pid) + ' (maliit-server) S ' + ' '.join(['0'] * 18 + ['12345']))
            self.assertEqual(projected_apps(tmp, workers=True), {101: '12345'})
    def test_stubborn_owned_client_is_force_stopped(self):
        with patch('carplay_proto.display.projected_apps',return_value={101:'same'}), patch('os.kill') as kill:
            stop_projected_apps(grace=0)
            self.assertEqual(kill.call_args_list[0].args,(101,signal.SIGTERM))
            self.assertEqual(kill.call_args_list[1].args,(101,signal.SIGKILL))
    def test_unstarted_pipeline_cannot_clean_another_session(self):
        with patch('carplay_proto.display.stop_projected_apps') as stop, patch('time.sleep'):
            p=DisplayPipeline();p.close();p.close()
            stop.assert_not_called()
    def test_unmarked_compositor_preserves_its_clients(self):
        with patch('os.open', return_value=9), patch('fcntl.flock'), patch('os.close') as close, \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='123\n')), \
             patch('carplay_proto.display.projected_apps', return_value={}), \
             patch('carplay_proto.display.stop_projected_apps') as stop:
            pipeline = DisplayPipeline()
            with self.assertRaisesRegex(RuntimeError, 'existing compositor active'):
                pipeline.start()
            stop.assert_not_called()
            close.assert_called_once_with(9)
            self.assertIsNone(pipeline.lock_fd)
