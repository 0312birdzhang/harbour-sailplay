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
    def test_local_disconnect_command_has_explicit_reason(self):
        with patch.object(m.logging, 'info') as log:
            m.public_hci_metadata(2, struct.pack('<HBHB', 0x0406, 3, 42, 0x13))
        self.assertEqual(log.call_args.args[1:], (42, 0x13, 'remote user terminated'))
        self.assertIn('local Disconnect command', log.call_args.args[0])
    def test_disconnect_maps_peer_and_cleans_channel_state(self):
        monitor = m.Monitor.__new__(m.Monitor)
        monitor.peers, monitor.pending, monitor.rfcomm = {}, {(42, 'rx', 1): (3, 5)}, {(42, 5), (43, 6)}
        connection = b'\x03\x0b\x00' + struct.pack('<H', 42) + bytes.fromhex('92edaeada7ec') + b'\x01\x01'
        with patch.object(m.logging, 'info') as log:
            monitor.process(3, connection)
            self.assertEqual(monitor.peers[42], 'EC:A7:AD:AE:ED:92')
            monitor.process(3, b'\x05\x04' + struct.pack('<BHB', 0, 42, 0x16))
        self.assertEqual(log.call_args.args[1:], (42, 'EC:A7:AD:AE:ED:92', 0, 0x16, 'local host terminated'))
        self.assertFalse(monitor.peers)
        self.assertFalse(monitor.pending)
        self.assertEqual(monitor.rfcomm, {(43, 6)})
    def test_rfcomm_disc_is_logged_without_application_payload(self):
        monitor = m.Monitor.__new__(m.Monitor)
        monitor.peers, monitor.pending, monitor.rfcomm = {42: 'peer'}, {}, {(42, 5)}
        payload = b'\x09\x43\x01secret'
        acl = struct.pack('<HHHH', 42 | (2 << 12), len(payload) + 4, len(payload), 5) + payload
        with patch.object(m.logging, 'info') as log:
            monitor.process(5, acl)
        self.assertEqual(log.call_args.args[1:3], ('rx', 'DISC'))
        self.assertNotIn('secret', str(log.call_args))
    def test_endless_eir_rewrites_are_bounded_and_counted(self):
        now = [0.0]
        write = struct.pack('<HB', 0x0c52, 241) + bytes(241)
        with patch.object(m, 'eir_repeats', m.RepeatGate(burst=3, clock=lambda: now[0])), \
                patch.object(m.logging, 'info') as log:
            for _ in range(40):
                m.public_hci_metadata(2, write)
                m.public_hci_metadata(3, bytes.fromhex('0e0401520c00'))
            self.assertEqual(log.call_count, 6)
            now[0] = 61
            m.public_hci_metadata(2, write)
        self.assertEqual(log.call_args.args[-1], ' similarEventsNotLogged=37')
if __name__=='__main__':unittest.main()
