import tempfile
from pathlib import Path
import unittest
from carplay_proto.displaysettings import load_settings, display_modes, publish_display
from carplay_proto.display import DisplayPipeline


class ProjectionSettingsTests(unittest.TestCase):
    def test_missing_settings_preserve_default(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_settings(str(Path(directory) / 'absent')), (1920, 720, 30))

    def test_qsettings_ini_and_all_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'display.ini'
            for width, height in ((1920, 720), (1600, 600), (1280, 480)):
                for fps in (30, 60):
                    path.write_text('[Display]\nwidth={}\nheight={}\nfps={}\n'.format(width, height, fps))
                    self.assertEqual(load_settings(str(path)), (width, height, fps))

    def test_invalid_values_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'display.ini'
            for values in ('width=1920\nheight=480\nfps=60', 'width=1280\nheight=480\nfps=1000', 'fps=invalid'):
                path.write_text('[Display]\n' + values)
                self.assertEqual(load_settings(str(path)), (1920, 720, 30))

    def test_pipeline_preserves_selected_dimensions_and_fps(self):
        pipeline = DisplayPipeline(1280, 480, 60)
        self.assertEqual((pipeline.width, pipeline.height, pipeline.fps), (1280, 480, 60))

    def test_modes_follow_car_and_limit_frame_rate(self):
        display = {'widthPixels': 1280, 'heightPixels': 720, 'maxFPS': 30}
        self.assertEqual(display_modes(display), ((1280, 720), (1066, 600), (852, 480)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.ini'
            path.write_text('[Display]\nwidth=1920\nheight=720\nresolutionIndex=1\nfps=60\n')
            self.assertEqual(load_settings(str(path), display), (1066, 600, 30))
            display['maxFPS'] = 60
            self.assertEqual(load_settings(str(path), display), (1066, 600, 60))

    def test_missing_configuration_uses_native_car_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            display = {'widthPixels': 800, 'heightPixels': 480}
            path = Path(directory) / 'absent'
            self.assertEqual(load_settings(str(path), display), (800, 480, 30))
            publish_display(display, str(path))
            self.assertIn('width=800', path.read_text())
            self.assertIn('maxFPS=30', path.read_text())

    def test_invalid_car_dimensions_rejected(self):
        for width in (0, -1, 801, 100000):
            with self.assertRaises(ValueError):
                display_modes({'widthPixels': width, 'heightPixels': 480})
