import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('connection_monitor',
    Path(__file__).resolve().parents[1] / 'scripts' / 'connection-monitor.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConnectionMetadataTests(unittest.TestCase):
    def test_credential_setting_keeps_caller_metadata_and_redacts_value(self):
        metadata = module.public_method('net.connman.Service', '/service', 'SetProperty',
                                        ['Passphrase', 'never-save-this-secret'])
        self.assertEqual(metadata, {'property': 'Passphrase', 'value': '<redacted>'})
        self.assertNotIn('never-save', str(metadata))
        self.assertIsNone(module.public_method('net.connman.Agent', '/', 'RequestInput', ['secret']))

    def test_transient_unit_logs_name_without_environment_or_command(self):
        metadata = module.public_method('org.freedesktop.systemd1.Manager', '/', 'StartTransientUnit',
            ['sailplay-handover-123.service', 'replace', {'Environment': ['SECRET=value']}, []])
        self.assertEqual(metadata, {'unit': 'sailplay-handover-123.service'})
        self.assertIsNone(module.public_method('org.freedesktop.systemd1.Manager', '/', 'StopUnit',
                                               ['unrelated.service', 'replace']))

    def test_bluez_disconnect_and_remove_keep_public_target(self):
        self.assertEqual(module.public_method('org.bluez.Device1', '/device', 'Disconnect', []), {})
        self.assertEqual(module.public_method('org.bluez.Adapter1', '/adapter', 'RemoveDevice', ['/device']),
                         {'device': '/device'})

    def test_property_signals_are_limited_to_connection_state(self):
        metadata = module.public_signal('org.freedesktop.DBus.Properties', '/device', 'PropertiesChanged',
            ['org.bluez.Device1', {'Connected': False, 'Alias': 'personal name', 'LinkKey': 'secret'}, []])
        self.assertEqual(metadata, {'interface': 'org.bluez.Device1', 'properties': {'Connected': False}})
        self.assertIsNone(module.public_signal('org.freedesktop.DBus.Properties', '/music', 'PropertiesChanged',
                                               ['org.mpris.MediaPlayer2.Player', {'Metadata': 'song'}, []]))

    def test_byte_strength_stays_numeric_and_owner_changes_are_recorded(self):
        class Byte(int):
            def __str__(self):
                return chr(self)
        metadata = module.public_signal('net.connman.Service', '/service', 'PropertyChanged', ['Strength', Byte(72)])
        self.assertEqual(metadata['properties']['Strength'], 72)
        self.assertIs(type(metadata['properties']['Strength']), int)
        self.assertEqual(module.public_signal('org.freedesktop.DBus', '/', 'NameOwnerChanged',
            ['net.connman', ':1.20', ':1.30'])['newOwner'], ':1.30')

    def test_only_service_list_changes_of_an_adapter_count_as_churn(self):
        self.assertTrue(module.service_churn({'interface': 'org.bluez.Adapter1', 'properties': {'UUIDs': []}}))
        self.assertFalse(module.service_churn(
            {'interface': 'org.bluez.Adapter1', 'properties': {'UUIDs': [], 'Powered': True}}))
        self.assertFalse(module.service_churn({'interface': 'org.bluez.Device1', 'properties': {'UUIDs': []}}))
        self.assertFalse(module.service_churn({'name': 'org.bluez', 'oldOwner': '', 'newOwner': ':1.5'}))


if __name__ == '__main__':
    unittest.main()
