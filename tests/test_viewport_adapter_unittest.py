import importlib.util
from pathlib import Path
import unittest
spec = importlib.util.spec_from_file_location('adapter', Path(__file__).parents[1] / 'scripts/prepare-viewport-compat.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

class AdapterTests(unittest.TestCase):
    def source(self, base):
        return '\n'.join(['id: window',
            'readonly property real _screenWidth: stack.verticalOrientation ? '+base+'.width : '+base+'.height',
            'readonly property real _screenHeight: stack.verticalOrientation ? '+base+'.height : '+base+'.width',
            'width: Screen.width', 'height: Screen.height'])
    def test_old_and_current_silica(self):
        for base in ('Screen', 'contentArea'):
            result = adapter.adapt(self.source(base))
            self.assertIn('width: window._sailplayPortraitWidth',result)
            self.assertIn('_screenHeight: stack.verticalOrientation ? _sailplayPortraitHeight : _sailplayPortraitWidth',result)
    def test_unknown_or_duplicate_layout_rejected(self):
        for source in ('id: window', self.source('Screen')+'\nwidth: Screen.width'):
            with self.assertRaises(RuntimeError):adapter.adapt(source)
