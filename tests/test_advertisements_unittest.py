import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('phone_advertise',
    Path(__file__).resolve().parents[1] / 'scripts' / 'wireless-phone-advertise.py')
advertise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(advertise)


class AdvertisementTests(unittest.TestCase):
    def test_existing_carplay_marker_still_requires_iap2(self):
        self.assertEqual(advertise.missing_advertisements([advertise.PHONE_EIR]),
                         [advertise.IAP_V2_EIR])

    def test_preserves_existing_services_case_insensitively(self):
        existing = [advertise.PHONE_EIR.upper(), advertise.IAP_V2_EIR.upper(), 'other']
        self.assertEqual(advertise.missing_advertisements(existing), [])
        self.assertEqual(len(existing), 3)

    def test_both_required_when_absent(self):
        self.assertEqual(advertise.missing_advertisements([]),
                         [advertise.PHONE_EIR, advertise.IAP_V2_EIR])
