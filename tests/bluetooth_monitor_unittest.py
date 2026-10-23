import importlib.util
from pathlib import Path
import struct
import unittest
import uuid
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('monitor',Path(__file__).resolve().parents[1]/'scripts'/'bluetooth-monitor.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PublicHciTests(unittest.TestCase):
    def test_eir_keeps_service_uuids_not_names_or_vendor_data(self):
        marker='2d8d2466-e14d-451c-88bc-7301abea291a'
        data=b'\x07\x09secret'+bytes([17,7])+uuid.UUID(marker).bytes[::-1]+b'\x04\xffkey'+b'\x00'
        summary=m.eir_summary(data)
        self.assertEqual(summary,{'malformed':False,'uuids128':[marker]})
        self.assertNotIn('secret',str(summary));self.assertNotIn('key',str(summary))
    def test_truncated_uuid_is_reported_not_accepted(self):
        self.assertTrue(m.eir_summary(b'\x03\x07ab')['malformed'])
        self.assertTrue(m.eir_summary(b'\x11\x07ab')['malformed'])
    def test_write_and_controller_ack_are_separate_evidence(self):
        with patch.object(m.logging,'info') as log:
            m.public_hci_metadata(2,struct.pack('<HB',0x0c52,241)+bytes(241))
            m.public_hci_metadata(3,bytes.fromhex('0e0401520c0c'))
        self.assertEqual(log.call_count,2)
        self.assertEqual(log.call_args_list[1].args[1],12)
    def test_pairing_status_does_not_log_address_or_link_key(self):
        with patch.object(m.logging,'info') as log:
            m.public_hci_metadata(3,b'\x36\x07\x05'+b'secret')
            m.public_hci_metadata(3,b'\x18\x17'+b'k'*23)
        self.assertEqual(log.call_count,1)
        self.assertEqual(log.call_args.args[1:],(5,))
if __name__=='__main__':unittest.main()
