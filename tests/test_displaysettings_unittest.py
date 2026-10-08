import tempfile
from pathlib import Path
import unittest
from carplay_proto.displaysettings import load_settings
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
