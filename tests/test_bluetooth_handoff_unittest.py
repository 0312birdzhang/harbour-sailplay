import plistlib
import unittest
from unittest.mock import Mock
from carplay_proto.videodemo import disable_bluetooth

class HandoffTests(unittest.TestCase):
    def test_actual_local_address_and_command(self):
        client=Mock();client.request.return_value=(200,{},plistlib.dumps({'status':0}))
        disable_bluetooth(client,'ab:cd:ef:01:23:45')
        args=client.request.call_args.args
        self.assertEqual(args[:2],('POST','/command'))
        self.assertEqual(plistlib.loads(args[2]),{'type':'disableBluetooth','params':{'deviceID':'AB:CD:EF:01:23:45'}})
    def test_invalid_identity_never_sent(self):
        client=Mock()
        with self.assertRaises(ValueError):disable_bluetooth(client,'not-a-mac')
        client.request.assert_not_called()
    def test_protocol_rejection_is_not_success(self):
        client=Mock();client.request.return_value=(200,{},plistlib.dumps({'status':-1}))
        with self.assertRaises(RuntimeError):disable_bluetooth(client,'AB:CD:EF:01:23:45')
