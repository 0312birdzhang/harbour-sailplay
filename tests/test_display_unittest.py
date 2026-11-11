import unittest
import io
import signal
from types import SimpleNamespace
from unittest.mock import patch
from carplay_proto.display import AnnexBFrames, DisplayPipeline


class DisplayFramesTests(unittest.TestCase):
    def test_fragmented_multislice_waits_for_idr(self):
        units=[b'\x41\x80\xaa',b'\x67\x42\x00\x1f',b'\x68\x01',
               b'\x65\x80\xbb',b'\x65\x40\xcc',b'\x41\x80\xdd',
               b'\x41\x80\xee',b'\x09\xf0']
        stream=b''.join((b'\x00\x00\x01' if i%2 else b'\x00\x00\x00\x01')+n
                        for i,n in enumerate(units))
        parser=AnnexBFrames()
        frames=[]
        for byte in stream:
            frames.extend(parser.feed(bytes([byte])))
        self.assertEqual(frames,[[units[3],units[4]],[units[5]]])
        self.assertEqual(parser.config()[:6],b'\x01\x42\x00\x1f\xff\xe1')

    def test_unbounded_capture_input_rejected(self):
        with self.assertRaises(ValueError):
            AnnexBFrames().feed(bytes(8*1024*1024+1))

    def test_launch_keeps_su_child_in_the_pipeline_process_group(self):
        from unittest.mock import Mock
        with patch('builtins.open', return_value=Mock()), patch('subprocess.Popen') as launch:
            pipeline = DisplayPipeline()
            pipeline.launch('carui', 'env WAYLAND_DISPLAY=test /opt/sailplay/carui/carui')
            arguments = launch.call_args.args[0]
            self.assertEqual(arguments[4], '--session-command')
            self.assertIn('SAILPLAY_DISPLAY_PIPELINE=' + pipeline.fifo, arguments[5])
            self.assertTrue(launch.call_args.kwargs['start_new_session'])

    def test_projection_shell_uses_the_private_keyboard(self):
        from unittest.mock import Mock
        with patch('carplay_proto.display.os.open', return_value=1), \
             patch('carplay_proto.display.fcntl.flock'), \
             patch('carplay_proto.display.subprocess.run', return_value=SimpleNamespace(returncode=1)), \
             patch('carplay_proto.display.projected_apps', return_value={}), \
             patch('carplay_proto.display.stop_projected_apps'), \
             patch('carplay_proto.display.os.path.exists', return_value=True), \
             patch('carplay_proto.display.os.mkfifo'), \
             patch('carplay_proto.display.os.chmod'), \
             patch.object(DisplayPipeline, 'launch', return_value=Mock()) as launch:
            DisplayPipeline().start()
            command = next(call.args[1] for call in launch.call_args_list if call.args[0] == 'carui')
            self.assertIn('QT_IM_MODULE=Maliit', command)
            self.assertIn('MALIIT_SERVER_ADDRESS=unix:path=/run/user/100000/sailplay-maliit/socket', command)

    def test_keyframe_signals_only_owned_capture_child(self):
        pipeline = DisplayPipeline()
        pipeline.capture = SimpleNamespace(pid=100)
        def read(path, mode='r'):
            if path.endswith('/children'):
                return io.StringIO('101 102')
            if path == '/proc/101/cmdline':
                return io.BytesIO(b'carlife-capture\0--out\0/unrelated\0')
            return io.BytesIO(b'carlife-capture\0--out\0' + pipeline.fifo.encode() + b'\0')
        with patch('carplay_proto.display.os.path.exists', return_value=True), \
             patch('builtins.open', side_effect=read), \
             patch('os.readlink', side_effect=lambda path: '/usr/bin/su' if path == '/proc/100/exe' else '/opt/sailplay/carlife-capture'), \
             patch('os.kill') as kill:
            pipeline.request_keyframe()
            kill.assert_called_once_with(102, signal.SIGUSR1)

    def test_keyframe_never_signals_unrelated_process(self):
        pipeline = DisplayPipeline()
        pipeline.capture = SimpleNamespace(pid=100)
        with patch('carplay_proto.display.os.path.exists', return_value=True), \
             patch('builtins.open', return_value=io.StringIO('')), \
             patch('os.readlink', return_value='/usr/bin/su'), patch('os.kill') as kill:
            with self.assertRaises(RuntimeError):
                pipeline.request_keyframe()
            kill.assert_not_called()

    def test_dead_shell_is_not_treated_as_healthy_video(self):
        from unittest.mock import Mock
        pipeline=DisplayPipeline();pipeline.ui=Mock(returncode=1)
        pipeline.ui.poll.return_value=1
        with self.assertRaisesRegex(RuntimeError,'carui exited'):
            pipeline.check_health()
