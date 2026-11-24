import importlib.util
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('bridge_install',Path(__file__).parents[1]/'scripts/install-system-media-bridge.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)

class BridgeTests(unittest.TestCase):
    def test_install_idempotent_and_restore_preserves_external_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'mediaplayer.qml';state=root/'state'
            original='ApplicationWindow {\n    id: app\n}\n'
            target.write_text(original)
            self.assertEqual(bridge.update(target,state),'installed')
            self.assertEqual(bridge.update(target,state),'unchanged')
            self.assertEqual((state/'mediaplayer.qml.original').read_text(),original)
            target.write_text(target.read_text()+'// external change\n')
            bridge.update(target,state,True)
            self.assertEqual(target.read_text(),original+'// external change\n')

    def test_unknown_source_and_existing_temporary_file_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'mediaplayer.qml';state=root/'state'
            target.write_text('unknown source')
            with self.assertRaises(ValueError):bridge.update(target,state)
            self.assertEqual(target.read_text(),'unknown source')
            target.write_text('ApplicationWindow {\n    id: app\n}\n')
            temporary=root/'mediaplayer.qml.sailplay-tmp';temporary.write_text('unexpected file')
            with self.assertRaises(FileExistsError):bridge.update(target,state)
            self.assertEqual(temporary.read_text(),'unexpected file')
