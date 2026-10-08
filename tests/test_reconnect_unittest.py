import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('reconnect_car',
    Path(__file__).resolve().parents[1] / 'scripts' / 'reconnect-car.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConfiguredHeadUnitTests(unittest.TestCase):
    def test_extracts_device_from_systemd_execstart(self):
        target = '/org/bluez/hci1/dev_EC_A7_AD_81_EA_86'
        self.assertEqual(module.configured_device(
            'ExecStart={ path=/usr/bin/python3 ; argv[]=python3 probe --device ' + target + ' --sustained ; }'), target)

    def test_missing_target_does_not_connect_arbitrary_bonded_device(self):
        with self.assertRaises(RuntimeError):
            module.configured_device('ExecStart=python3 probe --seconds 0')
