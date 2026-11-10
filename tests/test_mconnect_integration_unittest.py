import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mconnect_integration', ROOT / 'sdk/integrations/mconnect/apply.py')
integration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integration)


def digest(value):
    return hashlib.sha256(value).hexdigest()


@unittest.skipUnless(shutil.which('git'), 'Git is required for the source integration')
class MconnectIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sailplay-integration-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.checkout = self.root / 'checkout'
        self.bundle = self.root / 'bundle'
        self.sdk = self.root / 'sdk'
        for directory in (self.checkout, self.bundle, self.sdk):
            directory.mkdir()
        self.native = self.checkout / 'apps/mconnect/native.cpp'
        self.native.parent.mkdir(parents=True)
        self.native.write_bytes(b'before\n')
        self.document = self.checkout / 'apps/mconnect/docs/background.md'
        self.overlay = self.checkout / 'apps/mconnect/elinux/sailplay-sdk/provider.h'
        (self.sdk / 'provider.h').write_bytes(b'provider\n')
        self.patch = b'''diff --git a/apps/mconnect/native.cpp b/apps/mconnect/native.cpp
--- a/apps/mconnect/native.cpp
+++ b/apps/mconnect/native.cpp
@@ -1 +1 @@
-before
+after
diff --git a/apps/mconnect/docs/background.md b/apps/mconnect/docs/background.md
new file mode 100644
--- /dev/null
+++ b/apps/mconnect/docs/background.md
@@ -0,0 +1 @@
+Background lifecycle
'''
        (self.bundle / 'lifecycle.patch').write_bytes(self.patch)
        manifest = {'patch_sha256': digest(self.patch), 'files': [
            {'path': 'apps/mconnect/native.cpp', 'before_sha256': digest(b'before\n'),
             'after_sha256': digest(b'after\n')},
            {'path': 'apps/mconnect/docs/background.md', 'before_sha256': None,
             'after_sha256': digest(b'Background lifecycle\n')}],
            'sdk_files': [{'source': 'provider.h', 'path': 'apps/mconnect/elinux/sailplay-sdk/provider.h',
                           'sha256': digest(b'provider\n')}]}
        (self.bundle / 'baseline.json').write_text(json.dumps(manifest), encoding='utf-8')
        for name, value in (('HERE', self.bundle), ('SDK_REPO', self.sdk)):
            patcher = mock.patch.object(integration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_application_ignores_checkout_line_ending_rules(self):
        subprocess.run(['git', 'init', '--quiet', str(self.checkout)], check=True)
        subprocess.run(['git', '-C', str(self.checkout), 'config', 'core.autocrlf', 'true'], check=True)
        (self.checkout / '.gitattributes').write_bytes(b'*.md text eol=crlf\n')
        self.assertEqual(integration.apply(self.checkout, check=True)['source'], 'baseline')
        self.assertFalse(self.document.exists())
        self.assertEqual(integration.apply(self.checkout), {'source': 'applied', 'verified_files': 3})
        self.assertEqual(self.native.read_bytes(), b'after\n')
        self.assertEqual(self.document.read_bytes(), b'Background lifecycle\n')
        self.assertEqual(self.overlay.read_bytes(), b'provider\n')
        self.assertEqual(integration.apply(self.checkout)['source'], 'applied')
        self.assertEqual((self.checkout / '.gitattributes').read_bytes(), b'*.md text eol=crlf\n')

    def test_mismatch_preserves_existing_files(self):
        self.native.write_bytes(b'user edit\n')
        with self.assertRaises(RuntimeError):
            integration.apply(self.checkout)
        self.assertEqual(self.native.read_bytes(), b'user edit\n')
        self.assertFalse(self.document.exists())
        self.assertFalse(self.overlay.exists())

    def test_atomic_rollback_preserves_concurrent_edit(self):
        original_write = integration.write_atomic

        def failing_write(path, data, directories):
            if path == self.overlay:
                self.native.write_bytes(b'concurrent edit\n')
                raise RuntimeError('Injected overlay failure')
            return original_write(path, data, directories)

        with mock.patch.object(integration, 'write_atomic', failing_write):
            with self.assertRaises(RuntimeError):
                integration.apply(self.checkout)
        self.assertEqual(self.native.read_bytes(), b'concurrent edit\n')
        self.assertFalse(self.document.exists())
        self.assertFalse(self.overlay.exists())
        self.assertFalse(self.document.parent.exists())

    def test_application_uses_validated_patch_bytes(self):
        original_run = subprocess.run

        def changed_patch(arguments, **options):
            if arguments[0] == 'git' and 'apply' in arguments:
                (self.bundle / 'lifecycle.patch').write_bytes(b'concurrent patch edit\n')
                self.assertEqual(options['input'], self.patch)
            return original_run(arguments, **options)

        with mock.patch.object(integration.subprocess, 'run', changed_patch):
            self.assertEqual(integration.apply(self.checkout)['verified_files'], 3)
        self.assertEqual(self.native.read_bytes(), b'after\n')
        self.assertEqual(self.document.read_bytes(), b'Background lifecycle\n')

    def test_rollback_preserves_files_written_by_another_application(self):
        original_write = integration.write_atomic

        def concurrent_write(path, data, directories):
            original_write(path, data, directories)
            if path == self.native and data == b'after\n':
                self.document.parent.mkdir(parents=True)
                self.document.write_bytes(b'Background lifecycle\n')
                self.overlay.parent.mkdir(parents=True)
                self.overlay.write_bytes(b'provider\n')

        with mock.patch.object(integration, 'write_atomic', concurrent_write):
            with self.assertRaisesRegex(RuntimeError, 'changed during application'):
                integration.apply(self.checkout)
        self.assertEqual(self.native.read_bytes(), b'before\n')
        self.assertEqual(self.document.read_bytes(), b'Background lifecycle\n')
        self.assertEqual(self.overlay.read_bytes(), b'provider\n')


if __name__ == '__main__':
    unittest.main()
