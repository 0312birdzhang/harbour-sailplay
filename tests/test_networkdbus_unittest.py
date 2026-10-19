import unittest
from unittest.mock import Mock
from carplay_proto.networkdbus import BoundedInterface, network_object

class NetworkRpcTests(unittest.TestCase):
    def test_proxy_follows_replacement_without_an_introspection_rpc(self):
        bus=Mock()
        network_object(bus,'net.connman','/')
        bus.get_object.assert_called_once_with('net.connman','/',introspect=False,follow_name_owner_changes=True)

    def test_sync_calls_have_a_bound(self):
        native=Mock();wrapper=BoundedInterface(native)
        wrapper.GetProperties()
        native.GetProperties.assert_called_once_with(timeout=3)

    def test_async_connection_deadline_and_callbacks_are_preserved(self):
        native=Mock();wrapper=BoundedInterface(native)
        reply,error=Mock(),Mock()
        wrapper.Connect(reply_handler=reply,error_handler=error,timeout=12)
        native.Connect.assert_called_once_with(reply_handler=reply,error_handler=error,timeout=12)
