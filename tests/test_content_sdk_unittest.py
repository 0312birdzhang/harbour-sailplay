"""Content1 page bounds, queries and transport contracts."""
import copy
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import unittest
import tempfile

from sailplay_sdk.content_model import content_item, content_page, validate_content, validate_query
from sailplay_sdk.contract import CONTENT_INTERFACE, signatures
from sailplay_sdk.model import Fault
from sailplay_sdk.discovery import read_declaration


class ContentTests(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(signatures(CONTENT_INTERFACE, 'GetContent'), ('', 'ta{sv}'))
        self.assertEqual(signatures(CONTENT_INTERFACE, 'ContentChanged', 'signal'), ('', 'ta{sv}'))

    def test_page_copies_inputs_and_supports_unicode(self):
        item = content_item('歌曲', '🚗' * 1024, kind='action', action='music.select', parameters={'index': 1})
        value = content_page(items=[item], actions=[item], message='提示', message_kind='info')
        item['parameters']['index'] = 2
        self.assertEqual(value['items'][0]['parameters'], {'index': 1})
        self.assertEqual(validate_content(value), value)

    def test_missing_unknown_and_invalid_fields(self):
        page = content_page()
        for key in page:
            value = copy.deepcopy(page)
            del value[key]
            with self.subTest(key=key), self.assertRaises(Fault):
                validate_content(value)
        cases = (('id', ''), ('id', 'x' * 257), ('title', 'x\0y'), ('items', {}),
                 ('messageKind', 'html'), ('messageKind', []), ('offset', True), ('offset', -1),
                 ('offset', 1 << 32), ('searchEnabled', 1), ('hasMore', True), ('unknown', 1))
        for key, invalid in cases:
            with self.subTest(key=key, invalid=invalid), self.assertRaises(Fault):
                validate_content(dict(page, **{key: invalid}))

    def test_items_and_action_controls_are_bounded(self):
        items = [content_item(str(index), 'Item') for index in range(51)]
        self.assertEqual(len(content_page(items=items[:50])['items']), 50)
        for values in (items, items[:1] * 2):
            with self.assertRaises(Fault):
                content_page(items=values)
        with self.assertRaises(Fault):
            content_page(actions=items[:1])
        actions = [content_item(str(index), 'Action', kind='action', action='action') for index in range(5)]
        with self.assertRaises(Fault):
            content_page(actions=actions)

    def test_action_fields(self):
        for changes in ({'action': 'run'}, {'kind': 'action'}, {'enabled': 0}, {'parameters': []}, {'kind': None}):
            value = dict(content_item('item', 'Item'), **changes)
            with self.subTest(changes=changes), self.assertRaises(Fault):
                content_page(items=[value])

    def test_pagination_must_advance_without_overflow(self):
        item = content_item('item', 'Item')
        self.assertTrue(content_page(items=[item], has_more=True)['hasMore'])
        with self.assertRaises(Fault):
            content_page(items=[item], offset=(1 << 32) - 1, has_more=True)
        self.assertEqual(content_page(version=(1 << 64) - 1)['version'], (1 << 64) - 1)
        with self.assertRaises(Fault):
            content_page(version=1 << 64)

    def test_queries_require_fixed_fields(self):
        value = {'id': 'root', 'offset': 0, 'limit': 50}
        self.assertEqual(validate_query(value), value)
        self.assertEqual(validate_query(dict(value, query='Unicode 中文'), True)['query'], 'Unicode 中文')
        for changes in ({'id': ''}, {'offset': True}, {'limit': 0}, {'limit': 51}, {'query': 'unexpected'}):
            with self.subTest(changes=changes), self.assertRaises(Fault):
                validate_query(dict(value, **changes))
        for query in ('', 'x' * 257, 'x\0y', None):
            with self.assertRaises(Fault):
                validate_query(dict(value, query=query), True)

    def test_alias_keeps_launcher_and_backend_identities(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'music-shortcut.desktop'
            text = ('[Desktop Entry]\nType=Application\nName=Music\nX-Sailplay-ApiVersion=1\n'
                    'X-Sailplay-Service=org.example.Music\nX-Sailplay-Capabilities=content;\n'
                    'X-Sailplay-ApplicationId=music-core\n')
            path.write_text(text, encoding='utf-8')
            declaration = read_declaration(path)
            self.assertEqual(declaration.application_id, 'music-core')
            self.assertEqual(declaration.desktop_id, 'music-shortcut')
            self.assertTrue(declaration.content_template)
            path.write_text(text.replace('music-core', '../music-core'), encoding='utf-8')
            self.assertIsNone(read_declaration(path))


@unittest.skipUnless(shutil.which('dbus-run-session') and importlib.util.find_spec('dbus')
                     and importlib.util.find_spec('gi'), 'D-Bus and GLib are required')
class ContentBusTests(unittest.TestCase):
    def test_reference_provider_and_clients(self):
        root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE='1')
        process = subprocess.Popen(['dbus-run-session', '--', sys.executable,
            str(root / 'tests/content_bus_scenario.py')], env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            output, _ = process.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            output, _ = process.communicate(timeout=5)
            self.fail('Content bus scenario timed out\n' + output)
        self.assertEqual(process.returncode, 0, output)
        self.assertIn('CONTENT_BUS_PASS', output)
