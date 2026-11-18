"""Car day/night state, protocol callbacks and disconnect ownership."""
import configparser
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from android_auto.protobuf import Message, field
from android_auto.session import Session
from android_auto.transport import Packet
from carplay_proto.vehicletheme import VehicleTheme
from test_android_auto_unittest import FakeTransport, discovery_payload


class VehicleThemeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'vehicle' / 'state.ini'
        self.theme = VehicleTheme('carplay', self.path)
        self.addCleanup(self.theme.close)

    def state(self):
        state = configparser.ConfigParser()
        state.read(self.path)
        return state['Vehicle']

    def test_unknown_start_atomic_updates_and_disconnect(self):
        self.theme.start()
        self.assertEqual(self.state()['NightMode'], 'unknown')
        self.assertEqual(self.state()['PID'], str(os.getpid()))
        stat = Path('/proc/self/stat').read_text()
        self.assertEqual(self.state()['StartTime'], stat[stat.rindex(')') + 2:].split()[19])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)
        for night in (True, False, True):
            previous_inode = self.path.stat().st_ino
            self.theme.update(night)
            self.assertEqual(self.state()['NightMode'], str(night).lower())
            self.assertNotEqual(self.path.stat().st_ino, previous_inode)
            self.assertEqual(list(self.path.parent.glob('.state-*')), [])
        previous_inode = self.path.stat().st_ino
        self.theme.update(True)
        self.assertEqual(self.path.stat().st_ino, previous_inode)
        self.theme.close()
        self.assertFalse(self.path.exists())
        self.theme.update(False)
        self.theme.close()
        self.assertFalse(self.path.exists())

    def test_invalid_commands_preserve_the_last_state(self):
        self.theme.start()
        self.assertIsNone(self.theme.command({'type': 'forceKeyFrame'}))
        self.assertEqual(self.theme.command({'type': 'setNightMode', 'params': {'nightMode': True}}), {'status': 0})
        for value in (None, 0, 1, 'true', {}, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.theme.command({'type': 'setNightMode', 'params': {'nightMode': value}})
        self.assertEqual(self.state()['NightMode'], 'true')

    def test_previous_owner_cannot_change_or_remove_new_session_state(self):
        self.theme.start()
        newer = VehicleTheme('android-auto', self.path)
        self.addCleanup(newer.close)
        with self.assertRaises(BlockingIOError):
            newer.start()
        self.theme.owner.close()
        self.theme.owner = None
        newer.start()
        newer.update(False)
        content = self.path.read_bytes()
        self.theme.update(True)
        self.theme.close()
        self.assertEqual(self.path.read_bytes(), content)
        self.assertEqual(self.state()['Session'], newer.session)

    def test_modified_and_missing_state_is_preserved(self):
        self.theme.start()
        self.path.write_bytes(b'unexpected content\n')
        self.theme.update(True)
        self.theme.close()
        self.assertEqual(self.path.read_bytes(), b'unexpected content\n')
        self.theme.start()
        self.path.unlink()
        self.theme.update(True)
        self.theme.close()
        self.assertFalse(self.path.exists())

    def test_failed_replace_preserves_previous_state_and_cleans_temporary(self):
        self.theme.start()
        previous = self.path.read_bytes()
        with patch('carplay_proto.vehicletheme.os.replace', side_effect=OSError('failed replace')):
            with self.assertRaisesRegex(OSError, 'failed replace'):
                self.theme.update(True)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(self.theme.night, None)
        self.assertEqual(list(self.path.parent.glob('.state-*')), [])
        self.theme.update(True)
        self.assertEqual(self.state()['NightMode'], 'true')

    def test_carplay_normal_event_callback_updates_and_cleans_session_state(self):
        from carplay_proto.videodemo import run_demo
        client = Mock()
        client.request.return_value = (200, {}, b'')
        info = {'displays': [{'widthPixels': 1920, 'heightPixels': 720, 'uuid': 'display'}]}

        def event_connected(address, port, interface, shared, handler):
            self.assertEqual(self.state()['NightMode'], 'unknown')
            for night in (True, False):
                self.assertEqual(handler({'type': 'setNightMode', 'params': {'nightMode': night}}), {'status': 0})
                self.assertEqual(self.state()['NightMode'], str(night).lower())
            raise RuntimeError('stop after event callback')

        with patch('carplay_proto.vehicletheme.VehicleTheme', return_value=self.theme), \
             patch('carplay_proto.displaysettings.publish_display'), \
             patch('carplay_proto.displaysettings.load_settings', return_value=(1920, 720, 30)), \
             patch('carplay_proto.videodemo.DemoEvents', side_effect=event_connected), \
             patch('carplay_proto.mediakeys.MediaKeys'), \
             patch('carplay_proto.touch.TouchInput'), \
             patch('carplay_proto.projectionpower.ProjectionPower'):
            with self.assertRaisesRegex(RuntimeError, 'stop after event callback'):
                run_demo(client, 'receiver', None, bytes(32), {'eventPort': 1}, info, live=True)
        self.assertFalse(self.path.exists())


class AndroidAutoThemeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'state.ini'
        self.theme = VehicleTheme('android-auto', self.path)
        with patch('android_auto.session.VehicleTheme', return_value=self.theme):
            self.session = Session(FakeTransport(), None)
        self.addCleanup(self.session.close)

    def discovery(self, sensors=(10,), channel=41):
        sensor = field(1, channel) + field(2, b''.join(field(1, field(1, value)) for value in sensors))
        return discovery_payload() + field(1, sensor)

    def test_normal_run_subscribes_night_sensor_and_publishes_both_states(self):
        updates = []
        original = self.theme.update

        def update(night):
            original(night)
            updates.append(self.path.read_text())

        self.theme.update = update
        self.session.transport = FakeTransport([
            Packet(0, 6, self.discovery()), Packet(41, 8, field(1, 0)),
            Packet(41, 0x8002, field(1, 0)),
            Packet(41, 0x8003, field(10, field(1, 1))),
            Packet(41, 0x8003, field(10, field(1, 0))), Packet(0, 15, field(1, 1))])
        self.assertEqual(self.session.run(), 'user-exit')
        sent = self.session.transport.sent
        self.assertIn(41, [packet.channel for packet in sent if packet.type == 7])
        request = next(packet for packet in sent if packet.channel == 41 and packet.type == 0x8001)
        self.assertEqual(Message(request.payload).integer(1), 10)
        self.assertEqual(Message(request.payload).integer(2), 1000000)
        self.assertIn('NightMode=true', updates[0])
        self.assertIn('NightMode=false', updates[1])
        self.session.close()
        self.assertFalse(self.path.exists())

    def test_early_notifications_use_the_last_night_value(self):
        self.theme.start()
        self.session.handle(Packet(41, 0x8003, field(10, field(1, 1))))
        self.session.handle(Packet(0, 6, self.discovery()))
        self.assertTrue(self.theme.night)
        self.session.handle(Packet(41, 0x8003, field(10, field(1, 1)) + field(10, field(1, 0))))
        self.assertFalse(self.theme.night)

    def test_sensor_absent_or_rejected_does_not_end_projection(self):
        self.session.discover(self.discovery(sensors=(1,)))
        self.assertNotIn(41, self.session.requested)
        for channel in (17, 29, 23):
            self.session.channel_opened(channel, field(1, 0))
        self.assertTrue(self.session.running)
        self.session.discovery = None
        self.session.discover(self.discovery())
        self.session.channel_opened(41, field(1, -1))
        self.assertNotIn(41, self.session.requested)
        self.assertTrue(self.session.running)

    def test_invalid_value_and_unknown_channels_are_rejected(self):
        self.theme.start()
        self.session.discover(self.discovery())
        for packet in (Packet(41, 0x8003, field(10, field(1, 2))),
                       Packet(41, 0x8003, field(10, b'')), Packet(77, 0x8003, b'')):
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                self.session.handle(packet)
        self.assertIsNone(self.theme.night)

    def test_sensor_channel_close_and_transport_failure_clean_state(self):
        self.theme.start()
        self.session.discover(self.discovery())
        self.session.channel_opened(41, field(1, 0))
        self.session.handle(Packet(41, 9, b''))
        self.assertNotIn(41, self.session.opened)
        self.session.transport.close = Mock(side_effect=OSError('socket cleanup failed'))
        with self.assertRaisesRegex(OSError, 'socket cleanup failed'):
            self.session.close()
        self.assertFalse(self.path.exists())
        self.session.transport.close = Mock()
