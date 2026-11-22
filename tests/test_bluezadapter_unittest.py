import unittest
from unittest.mock import patch
from carplay_proto.bluezadapter import select_adapter, adapter_name, select_head_unit


class AdapterTests(unittest.TestCase):
    def test_name_prefers_user_alias_and_preserves_chinese(self):
        self.assertEqual(adapter_name({'Alias': '我的手机', 'Name': 'hardware'}), '我的手机')

    def test_name_falls_back_when_alias_is_empty(self):
        self.assertEqual(adapter_name({'Alias': '', 'Name': 'Jolla Phone'}), 'Jolla Phone')
        self.assertEqual(adapter_name({}), 'SailfishOS')

    def test_remap_target_when_hci0_is_not_exported(self):
        objects = {'/org/bluez/hci1': {'org.bluez.Adapter1': {'Powered': True}}}
        self.assertEqual(select_adapter(objects, '/org/bluez/hci0/dev_AB_CD'),
                         ('/org/bluez/hci1', '/org/bluez/hci1/dev_AB_CD'))

    def test_preserve_target_adapter_on_multi_adapter_device(self):
        objects = {path: {'org.bluez.Adapter1': {'Powered': True}}
                   for path in ('/org/bluez/hci0', '/org/bluez/hci1')}
        self.assertEqual(select_adapter(objects, '/org/bluez/hci1/dev_AB_CD')[0],
                         '/org/bluez/hci1')

    def test_prefer_powered_adapter_without_target(self):
        objects = {'/org/bluez/hci0': {'org.bluez.Adapter1': {'Powered': False}},
                   '/org/bluez/hci1': {'org.bluez.Adapter1': {'Powered': True}}}
        self.assertEqual(select_adapter(objects), ('/org/bluez/hci1', None))

    def test_no_adapter_is_explicit_error(self):
        with self.assertRaisesRegex(RuntimeError, 'No BlueZ'):
            select_adapter({})


class IgnoredAccessoryTests(unittest.TestCase):
    UUID = '00000000-deca-fade-deca-deafdecacaff'

    def device(self, connected=True):
        return {'org.bluez.Device1': {'Paired': True, 'Connected': connected, 'UUIDs': [self.UUID]}}

    def setUp(self):
        patcher = patch('carplay_proto.bluezadapter.authenticated_head_unit', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ignored_earbuds_do_not_replace_the_previous_vehicle(self):
        objects = {'/earbuds': self.device(), '/car': self.device(connected=False)}
        self.assertEqual(select_head_unit(objects, '/car', '/car'), '/earbuds')
        self.assertEqual(select_head_unit(objects, '/car', '/car', {'/earbuds'}), '/car')
        self.assertEqual(select_head_unit(objects, '/earbuds', '/car', {'/earbuds'}), '/car')

    def test_ignored_earbuds_do_not_make_a_connected_vehicle_ambiguous(self):
        objects = {'/earbuds': self.device(), '/car': self.device()}
        with self.assertRaises(RuntimeError):
            select_head_unit(objects, None, None)
        self.assertEqual(select_head_unit(objects, None, None, {'/earbuds'}), '/car')

    def test_ignored_previous_target_is_not_restored(self):
        objects = {'/earbuds': self.device()}
        self.assertIsNone(select_head_unit(objects, None, '/earbuds', {'/earbuds'}))
        self.assertEqual(select_head_unit(objects, None, '/earbuds'), '/earbuds')
