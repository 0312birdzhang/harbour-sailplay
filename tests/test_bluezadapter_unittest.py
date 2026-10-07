import unittest
from carplay_proto.bluezadapter import select_adapter


class AdapterTests(unittest.TestCase):
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
