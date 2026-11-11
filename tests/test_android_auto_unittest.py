"""Phone-role Android Auto framing, negotiation and lifecycle regressions."""
import collections
import datetime
import importlib.util
import io
import os
import queue
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from android_auto.bluez import AA_UUID, CARPLAY_UUID, select_head_unit
from android_auto.discovery import Discovery
from android_auto.input import InputHandler, letterbox
from android_auto.media import AudioProducer, MediaChannel, VideoProducer, adts_frame, annexb_config
from android_auto.network import NetworkHandover, connect_endpoint
from android_auto.protobuf import Message, field, varint
from android_auto.session import Session
from android_auto.transport import (ENCRYPTED, FIRST, LAST, FrameReader,
                                    MessageAssembler, Packet, Transport, frame, server_context)
from android_auto.wireless import Credentials, WppClient, WppReader, wpp_frame
from carplay_proto.networksession import restore_network, restore_previous_network
from carplay_proto.session import SessionBusy, SessionLease, current_owner, selected_protocol


def discovery_payload(video=17, input_channel=23, audio=29, codec=3):
    config = field(1, 2) + field(2, 2) + field(3, 0) + field(4, 240) + field(5, 160)
    sink = field(1, codec) + field(2, 0) + field(4, config)
    video_service = field(1, video) + field(3, sink)
    input_source = field(1, 85) + field(1, 66) + field(2, field(1, 1280) + field(2, 720))
    input_service = field(1, input_channel) + field(4, input_source)
    audio_config = field(1, 48000) + field(2, 16) + field(3, 2)
    audio_service = field(1, audio) + field(3, field(1, 1) + field(2, 3) + field(3, audio_config))
    return b''.join(field(1, service) for service in (video_service, input_service, audio_service)) + field(14, 'DiAuto')


def load_script(name):
    path = Path(__file__).resolve().parent.parent / 'scripts' / (name + '.py')
    specification = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class FakeProducer:
    def __init__(self, *args):
        self.queue = queue.Queue(2)
        self.generation = 0
        self.enabled = False
        self.error = None
        self.closed = False
        self.keyframes = 0
        self.gain = 1.0

    def set_enabled(self, value):
        if value != self.enabled:
            self.enabled = value
            self.generation += 1

    def request_keyframe(self):
        self.keyframes += 1

    def close(self):
        self.closed = True


class FakeTransport:
    def __init__(self, packets=()):
        self.sent = []
        self.packets = collections.deque(packets)
        self.closed = False
        self.handshaken = False

    def send(self, channel, message_type, payload=b''):
        self.sent.append(Packet(channel, message_type, payload))

    def handshake(self):
        self.handshaken = True

    def receive(self, timeout):
        return self.packets.popleft() if self.packets else None

    def close(self):
        self.closed = True


class ProtobufTests(unittest.TestCase):
    def test_wpp_negative_status_uses_int32_twos_complement(self):
        encoded = field(4, -8)
        self.assertEqual(encoded.hex(), '20f8ffffffffffffffff01')
        self.assertEqual(Message(encoded).integer(4, signed=True), -8)

    def test_unknown_fixed_fields_and_packed_configuration_indices(self):
        data = field(1, 'Sailplay') + b'\x51' + bytes(8) + b'\x5d' + bytes(4)
        self.assertEqual(Message(data).text(1), 'Sailplay')
        self.assertEqual(Message(field(3, varint(0) + varint(2))).integers(3), [0, 2])

    def test_malformed_protobuf_is_bounded(self):
        for data in (b'\x00', b'\x80', b'\x0a\x10a', b'\x08' + b'\xff' * 10, b'\x09abc'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Message(data)

    def test_integer_wire_types_and_ranges_are_checked(self):
        with self.assertRaises(ValueError):
            Message(field(1, b'bad')).integer(1)
        with self.assertRaises(ValueError):
            varint(1 << 64)


class FramingTests(unittest.TestCase):
    def test_stop_interrupts_a_fragmented_media_write(self):
        transport = Transport.__new__(Transport)
        transport.ready = True
        transport.stop = threading.Event()
        transport.sock = Mock()
        transport.sock.sendall.side_effect = lambda data: transport.stop.set()
        transport.tls = SimpleNamespace(write=lambda data: len(data))
        transport.outgoing = SimpleNamespace(read=lambda: b'encrypted')
        with self.assertRaises(InterruptedError):
            transport.send(17, 0, b'x' * 32768)
        transport.sock.sendall.assert_called_once()

    def test_codec_configuration_uses_media_flags_and_channel_open_uses_control(self):
        transport = Transport.__new__(Transport)
        transport.ready = True
        transport.stop = None
        transport.sock = Mock()
        transport.tls = SimpleNamespace(write=lambda data: len(data))
        transport.outgoing = SimpleNamespace(read=lambda: b'encrypted')
        for message_type, expected in ((0, 11), (1, 11), (7, 15)):
            transport.send(17, message_type, b'payload')
            reader = FrameReader()
            reader.feed(transport.sock.sendall.call_args[0][0])
            self.assertEqual(reader.next().flags, expected)

    def test_split_and_coalesced_tcp_frames(self):
        reader = FrameReader()
        wire = frame(17, 9, b'ab', 6) + frame(17, 10, b'cdef')
        fragments = []
        for byte in wire:
            reader.feed(bytes([byte]))
            fragment = reader.next()
            if fragment is not None:
                fragments.append(fragment)
        self.assertEqual([(item.flags, item.total) for item in fragments], [(9, 6), (10, None)])
        assembler = MessageAssembler()
        self.assertIsNone(assembler.add(fragments[0], b'ab'))
        packet = assembler.add(fragments[1], b'cdef')
        self.assertEqual(packet, Packet(17, 0x6162, b'cdef'))
        self.assertEqual(assembler.buffered, 0)

    def test_interleaved_channels_keep_independent_assemblies(self):
        reader = FrameReader()
        reader.feed(frame(17, 9, b'\x00\x00', 4) + frame(29, 11, b'\x80\x04')
                    + frame(17, 10, b'ab'))
        assembler = MessageAssembler()
        self.assertIsNone(assembler.add(reader.next(), b'\x00\x00'))
        self.assertEqual(assembler.add(reader.next(), b'\x80\x04').type, 0x8004)
        self.assertEqual(assembler.add(reader.next(), b'ab').payload, b'ab')

    def test_orphans_truncation_and_declared_length_are_rejected(self):
        for flags, data, total in ((10, b'ab', None), (9, b'abcdef', 3)):
            reader = FrameReader()
            reader.feed(frame(1, flags, data, total))
            with self.assertRaises(ValueError):
                MessageAssembler().add(reader.next(), data)
        reader = FrameReader()
        reader.feed(frame(1, 9, b'ab', 6) + frame(1, 10, b'cd'))
        assembler = MessageAssembler()
        assembler.add(reader.next(), b'ab')
        with self.assertRaises(ValueError):
            assembler.add(reader.next(), b'cd')

    def test_fragment_mode_cannot_change(self):
        reader = FrameReader()
        reader.feed(frame(1, 9, b'ab', 4) + frame(1, 14, b'cd'))
        assembler = MessageAssembler()
        assembler.add(reader.next(), b'ab')
        with self.assertRaises(ValueError):
            assembler.add(reader.next(), b'cd')

    def test_invalid_lengths_and_flags_are_rejected(self):
        for data in (b'\x00\x03\x00\x00', b'\x00\x80\x00\x01a', b'\x00\x09\x00\x01\xff\xff\xff\xffa'):
            reader = FrameReader()
            reader.feed(data)
            with self.assertRaises(ValueError):
                reader.next()


class WirelessTests(unittest.TestCase):
    def test_wpp_header_matches_diauto_byte_order(self):
        self.assertEqual(wpp_frame(8, b'abc'), b'\x00\x03\x00\x08abc')
        reader = WppReader()
        reader.feed(wpp_frame(4) + wpp_frame(1, b'a'))
        self.assertEqual(reader.next(), (4, b''))
        self.assertEqual(reader.next(), (1, b'a'))

    def test_optional_version_ping_and_supplied_endpoint(self):
        phone, headunit = socket.socketpair()
        stop = threading.Event()
        client = WppClient(phone, stop)
        network = field(1, 'DiAutoAP') + field(2, 'password8') + field(3, '12:34:56:78:90:ab') + field(4, 8) + field(5, 1)
        headunit.sendall(wpp_frame(4, field(1, 1) + field(2, 1))
                         + wpp_frame(8, b'ping')
                         + wpp_frame(1, field(1, '192.168.44.1') + field(2, 65000))
                         + wpp_frame(3, network))
        credentials = client.negotiate('Sailplay')
        self.assertEqual((credentials.address, credentials.port), ('192.168.44.1', 65000))
        self.assertEqual((credentials.ssid, credentials.password), ('DiAutoAP', 'password8'))
        reader = WppReader()
        reader.feed(headunit.recv(4096))
        responses = []
        while True:
            response = reader.next()
            if response is None:
                break
            responses.append(response)
        self.assertEqual([item[0] for item in responses], [5, 9, 2, 7])
        self.assertEqual(responses[1][1], b'ping')
        self.assertEqual(Message(responses[0][1]).integer(4, signed=True), 0)
        phone.close()
        headunit.close()

    def test_invalid_endpoint_cannot_change_wifi(self):
        for address in ('127.0.0.1', '0.0.0.0', '224.0.0.1'):
            phone, headunit = socket.socketpair()
            headunit.sendall(wpp_frame(1, field(1, address) + field(2, 5288)))
            with self.assertRaises(ValueError):
                WppClient(phone, threading.Event()).negotiate()
            phone.close()
            headunit.close()

    def test_network_credentials_are_validated(self):
        for payload in (field(1, 'AP') + field(2, 'short'), field(1, 'A' * 33) + field(2, 'password8')):
            with self.assertRaises(ValueError):
                Credentials(('192.168.44.1', 5288), payload)

    def test_auto_prefers_carplay_for_dual_protocol_headunit(self):
        objects = {'/dual': {'org.bluez.Device1': {'Paired': True, 'Connected': True,
                                                  'UUIDs': [AA_UUID, CARPLAY_UUID]}}}
        self.assertIsNone(select_head_unit(objects, '/dual'))
        self.assertEqual(select_head_unit(objects, '/dual', protocol='android-auto'), '/dual')
        objects['/aa'] = {'org.bluez.Device1': {'Paired': True, 'Connected': True, 'UUIDs': [AA_UUID]}}
        self.assertEqual(select_head_unit(objects, '/dual'), '/aa')


class NegotiationTests(unittest.TestCase):
    def test_delayed_acknowledgements_preserve_a_progressing_media_window(self):
        service = Discovery(discovery_payload()).video
        media = MediaChannel(service, service.configs[0], FakeProducer())
        media.started = True
        media.session_id = 1
        media.sent.extend([time.monotonic() - 20, time.monotonic() - 19])
        media.acknowledge(field(1, 1) + field(2, 1))
        self.assertFalse(media.pump(FakeTransport()))
        media.last_acknowledged_at = time.monotonic() - 20
        with self.assertRaises(TimeoutError):
            media.pump(FakeTransport())

    def test_service_ids_and_margins_come_from_discovery(self):
        discovery = Discovery(discovery_payload())
        self.assertEqual((discovery.video.id, discovery.input.id, discovery.audio.id), (17, 23, 29))
        config = discovery.video.configs[0]
        self.assertEqual((config.width, config.height, config.margin_height), (1280, 720, 240))

    def test_duplicate_channels_and_unsupported_video_are_rejected(self):
        with self.assertRaises(ValueError):
            Discovery(discovery_payload(video=23))
        with self.assertRaises(ValueError):
            Discovery(discovery_payload(codec=7))

    def test_config_ack_credit_and_old_session_ack(self):
        service = Discovery(discovery_payload()).video
        producer, transport = FakeProducer(), FakeTransport()
        media = MediaChannel(service, service.configs[0], producer)
        media.configure(field(1, 2) + field(2, 1) + field(3, 0))
        media.start(transport)
        producer.queue.put((producer.generation, b'config', b'frame', 123))
        self.assertTrue(media.pump(transport))
        self.assertEqual(transport.sent[-1].type, 1)
        self.assertFalse(media.pump(transport))
        media.acknowledge(field(1, media.session_id + 1) + field(2, 1))
        self.assertFalse(media.pump(transport))
        media.acknowledge(field(1, media.session_id) + field(2, 1))
        self.assertTrue(media.pump(transport))
        self.assertEqual(transport.sent[-1], Packet(17, 0, struct.pack('>Q', 123) + b'frame'))

    def test_restarted_stream_drops_pending_media_and_changes_session(self):
        service = Discovery(discovery_payload()).video
        producer, transport = FakeProducer(), FakeTransport()
        media = MediaChannel(service, service.configs[0], producer)
        media.configure(field(1, 2) + field(2, 1) + field(3, 0))
        media.start(transport)
        first_session = media.session_id
        producer.queue.put((producer.generation, None, b'old', 123))
        media.stop(transport)
        media.start(transport)
        self.assertGreater(media.session_id, first_session)
        self.assertFalse(media.pump(transport))

    def test_avcc_and_adts_match_wire_configuration(self):
        avcc = b'\x01\x42\x00\x1e\xff\xe1\x00\x04\x67\x42\x00\x1e\x01\x00\x02\x68\x01'
        self.assertEqual(annexb_config(avcc), b'\x00\x00\x00\x01\x67\x42\x00\x1e\x00\x00\x00\x01\x68\x01')
        adts = adts_frame(b'abc')
        size = (adts[3] & 3) << 11 | adts[4] << 3 | adts[5] >> 5
        self.assertEqual((size, adts[7:]), (10, b'abc'))


class InputTests(unittest.TestCase):
    def test_letterbox_matches_capture_converter_even_offsets(self):
        self.assertEqual(letterbox(1280, 720, 1280, 480), (0, 120, 1280, 480))
        self.assertEqual(letterbox(720, 1280, 480, 1280), (120, 0, 480, 1280))

    def test_primary_pointer_cancel_and_release_are_display_scoped(self):
        discovery = Discovery(discovery_payload())
        handler = InputHandler(discovery.input, discovery.video.configs[0], 1280, 480, path='/missing')
        sent = []
        handler.send = sent.append
        pointer = field(1, 640) + field(2, 360) + field(3, 7)
        handler.report(field(1, 1) + field(3, field(1, pointer) + field(3, 0)))
        self.assertEqual(sent[-1], 'T 1 640 240')
        handler.report(field(1, 2) + field(3, field(3, 3)))
        self.assertEqual(sent[-1], 'T 0 640 240')
        handler.close()

    def test_media_repeat_is_debounced_and_keyboard_release_is_sent(self):
        discovery = Discovery(discovery_payload())
        media = SimpleNamespace(pending=queue.Queue(2))
        handler = InputHandler(discovery.input, discovery.video.configs[0], 1280, 480, media)
        sent = []
        handler.send = sent.append
        handler.key(85, 1)
        handler.key(85, 1)
        self.assertEqual(media.pending.qsize(), 1)
        handler.key(66, 1)
        handler.close()
        self.assertEqual(sent, ['K 1 28', 'K 0 28'])


class OwnershipTests(unittest.TestCase):
    def test_failed_journal_replacement_retains_the_previous_network_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/lock'
            lease = SessionLease('android-auto', path, None)
            lease.acquire()
            lease.plan_network('/home', '/car')
            with patch('carplay_proto.session.os.replace', side_effect=OSError('write failed')):
                with self.assertRaises(OSError):
                    lease.network_restored()
            self.assertEqual(current_owner(path)['network']['old'], '/home')
            self.assertEqual(list(Path(directory).glob('.sailplay-owner-*')), [])
            self.assertEqual(lease.state['network']['old'], '/home')
            lease.close()
            self.assertEqual(current_owner(path)['network']['old'], '/home')

    def test_dual_protocol_contention_and_stale_restore_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/lock'
            carplay = SessionLease('carplay', path, None)
            carplay.acquire()
            carplay.plan_network('/home', '/carplay')
            android = SessionLease('android-auto', path, None)
            with self.assertRaises(SessionBusy):
                android.acquire()
            old_identity = carplay.identity
            carplay.close()
            android.acquire()
            self.assertEqual(android.state['network']['old'], '/home')
            restoration = SessionLease('carplay', path, None)
            self.assertFalse(restoration.acquire(expected=old_identity))
            android.close()
            self.assertFalse(restoration.acquire(expected=old_identity))

    def test_failed_network_restore_preserves_recovery_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = SessionLease('android-auto', directory + '/lock', None)
            lease.acquire()
            lease.plan_network('/home', '/car')
            manager = SimpleNamespace(GetServices=lambda: [('/home', {'State': 'idle'}), ('/car', {'State': 'ready'})])
            car = SimpleNamespace(Disconnect=lambda: None)
            def failed_connect(**kwargs):
                raise RuntimeError('association failed')
            home = SimpleNamespace(Connect=failed_connect)
            objects = {'/': manager, '/home': home, '/car': car}
            with patch('carplay_proto.networksession.network_object', side_effect=lambda bus, name, path: objects[path]), \
                    patch('carplay_proto.networksession.network_interface', side_effect=lambda obj, name: obj):
                with self.assertRaises(RuntimeError):
                    restore_network(lease, None)
            self.assertEqual(lease.state['network']['old'], '/home')
            lease.close()

    def test_existing_empty_carplay_lock_and_protocol_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/lock'
            Path(path).touch()
            with SessionLease('carplay', path, None) as lease:
                self.assertIsNone(lease.state['network'])
            setting = directory + '/projection.ini'
            self.assertEqual(selected_protocol(setting), 'auto')
            Path(setting).write_text('[Projection]\nprotocol=android-auto\n')
            self.assertEqual(selected_protocol(setting), 'android-auto')


class LegacyNetworkTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lease = SessionLease('android-auto', directory.name + '/lock', None)
        self.lease.acquire()
        self.addCleanup(self.lease.close)
        self.home_path = '/net/connman/service/wifi_home'
        self.car_path = '/net/connman/service/wifi_car'
        self.other_path = '/net/connman/service/wifi_other'
        self.legacy_name = 'sailplay-wifi-restore-101.service'
        self.legacy_arguments = ['python3', '/opt/sailplay/scripts/wifi-session-probe.py',
                                 '--restore', self.home_path, self.car_path, '--restore-after', '45']
        modern_arguments = self.legacy_arguments + ['--session-id', 'modern-owner']
        legacy_values = {'ExecStart': [('python3', self.legacy_arguments)],
                         'ExecMainStartTimestampMonotonic': 100}
        self.legacy_properties = SimpleNamespace(Get=Mock(side_effect=lambda interface, name, **kwargs: legacy_values[name]))
        self.modern_properties = SimpleNamespace(Get=Mock(return_value=[('python3', modern_arguments)]))
        systemd = SimpleNamespace(ListUnits=Mock(return_value=[
            (self.legacy_name, '', 'loaded', 'active', 'running', '', '/legacy'),
            ('sailplay-wifi-restore-102.service', '', 'loaded', 'active', 'running', '', '/modern')]))
        self.manager = SimpleNamespace(GetServices=Mock(return_value=[
            (self.home_path, {'Type': 'wifi', 'State': 'idle'}),
            (self.car_path, {'Type': 'wifi', 'State': 'ready', 'Favorite': True}),
            (self.other_path, {'Type': 'wifi', 'State': 'idle'})]))
        self.home = SimpleNamespace(Connect=Mock())
        self.car = SimpleNamespace(Disconnect=Mock(), Remove=Mock())
        self.other = SimpleNamespace(Connect=Mock(), Disconnect=Mock())
        self.supplicant = SimpleNamespace(Set=Mock())
        objects = {'/org/freedesktop/systemd1': systemd, '/legacy': self.legacy_properties,
                   '/modern': self.modern_properties, '/': self.manager,
                   self.home_path: self.home, self.car_path: self.car, self.other_path: self.other,
                   '/fi/w1/wpa_supplicant1': self.supplicant}
        for target, values in (
                ('carplay_proto.networksession.network_object', {'side_effect': lambda bus, name, path: objects[path]}),
                ('carplay_proto.networksession.network_interface', {'side_effect': lambda obj, name: obj}),
                ('carplay_proto.networksession.subprocess.run', {})):
            replacement = patch(target, **values)
            value = replacement.start()
            self.addCleanup(replacement.stop)
            if target.endswith('subprocess.run'):
                self.stop = value

    def test_legacy_job_is_journaled_and_stopped_before_restoring_home(self):
        events = []

        def stopped(arguments, **kwargs):
            self.assertEqual(current_owner(self.lease.lock_path)['network']['old'], self.home_path)
            events.append('stop')

        self.stop.side_effect = stopped
        self.car.Disconnect.side_effect = lambda: events.append('disconnect')
        self.home.Connect.side_effect = lambda **kwargs: events.append('connect-home')
        restore_previous_network(self.lease, None, log=lambda message: None)
        self.assertEqual(events, ['stop', 'disconnect', 'connect-home'])
        self.stop.assert_called_once_with(['systemctl', 'stop', self.legacy_name], check=True, timeout=20)
        self.assertIsNone(self.lease.state['network'])

    def test_failed_legacy_job_stop_preserves_the_journal_for_retry(self):
        self.stop.side_effect = subprocess.TimeoutExpired('systemctl stop', 20)
        with self.assertRaises(subprocess.TimeoutExpired):
            restore_previous_network(self.lease, None, log=lambda message: None)
        self.assertEqual(current_owner(self.lease.lock_path)['network']['old'], self.home_path)
        self.car.Disconnect.assert_not_called()
        self.home.Connect.assert_not_called()

    def test_modern_jobs_and_user_selected_network_are_preserved(self):
        self.legacy_arguments.extend(['--restore-debug', 'info'])
        self.manager.GetServices.return_value = [
            (self.home_path, {'Type': 'wifi', 'State': 'idle'}),
            (self.car_path, {'Type': 'wifi', 'State': 'idle'}),
            (self.other_path, {'Type': 'wifi', 'State': 'ready'})]
        with patch.dict('sys.modules', {'dbus': SimpleNamespace(String=lambda value, **kwargs: value)}):
            restore_previous_network(self.lease, None, log=lambda message: None)
        self.stop.assert_called_once_with(['systemctl', 'stop', self.legacy_name], check=True, timeout=20)
        self.home.Connect.assert_not_called()
        self.car.Disconnect.assert_not_called()
        self.other.Connect.assert_not_called()
        self.other.Disconnect.assert_not_called()
        self.supplicant.Set.assert_called_once_with('fi.w1.wpa_supplicant1', 'DebugLevel', 'info')
        self.modern_properties.Get.assert_called_once_with('org.freedesktop.systemd1.Service', 'ExecStart', timeout=5)
        self.assertIsNone(self.lease.state['network'])


class SessionTests(unittest.TestCase):
    def test_bye_bye_response_is_the_last_message_even_with_queued_media(self):
        transport = FakeTransport([Packet(0, 15, field(1, 1))])
        session = Session(transport, None)
        service = Discovery(discovery_payload()).video
        producer = FakeProducer()
        media = MediaChannel(service, service.configs[0], producer)
        media.configured = True
        media.start(transport)
        producer.queue.put((producer.generation, None, b'queued-video', 123))
        session.media[17] = media
        self.assertEqual(session.run(), 'user-exit')
        self.assertEqual(transport.sent[-1].type, 16)
        self.assertFalse(any(packet.type == 0 for packet in transport.sent))
        session.close()

    def test_transport_close_failure_still_closes_all_media_and_input(self):
        transport = FakeTransport()
        transport.close = Mock(side_effect=OSError('socket cleanup failed'))
        producer = FakeProducer()
        inputs = SimpleNamespace(close=Mock())
        service = Discovery(discovery_payload()).video
        session = Session(transport, None)
        session.media[service.id] = MediaChannel(service, service.configs[0], producer)
        session.input = inputs
        with self.assertRaisesRegex(OSError, 'socket cleanup failed'):
            session.close()
        self.assertTrue(producer.closed)
        inputs.close.assert_called_once_with()
        self.assertEqual(session.media, {})

    def test_audio_focus_send_failure_keeps_producer_owned_for_cleanup(self):
        transport = FakeTransport()
        session = Session(transport, None, audio_factory=FakeProducer, publish=None)
        session.discover(discovery_payload())
        session.channel_opened(29, field(1, 0))
        transport.send = Mock(side_effect=OSError('focus send failed'))
        with self.assertRaisesRegex(OSError, 'focus send failed'):
            session.media_configured(29, field(1, 2) + field(2, 30) + field(3, 0))
        producer = session.media[29].producer
        session.close()
        self.assertTrue(producer.closed)

    def test_normal_session_entry_negotiates_headunit_channels(self):
        packets = [Packet(0, 6, discovery_payload()), Packet(17, 8, field(1, 0)),
                   Packet(23, 8, field(1, 0)), Packet(29, 8, field(1, 0)),
                   Packet(17, 0x8003, field(1, 2) + field(2, 12) + field(3, 0)),
                   Packet(17, 0x8008, field(1, 1) + field(2, 1)),
                   Packet(23, 0x8003, field(1, 0)), Packet(0, 15, field(1, 1))]
        with tempfile.TemporaryDirectory() as directory:
            lease = SessionLease('android-auto', directory + '/lock', None)
            lease.acquire()
            transport = FakeTransport(packets)
            inputs = []
            def make_input(*args):
                result = SimpleNamespace(release=lambda: None, report=inputs.append, close=lambda: None)
                return result
            session = Session(transport, lease, FakeProducer, FakeProducer, make_input, publish=None,
                              display_settings=directory + '/display.ini')
            self.assertEqual(session.run(), 'user-exit')
            self.assertTrue(transport.handshaken)
            self.assertEqual(transport.sent[0].type, 5)
            self.assertEqual([packet.channel for packet in transport.sent if packet.type == 7], [17, 29, 23])
            self.assertEqual(Message(next(packet.payload for packet in transport.sent if packet.type == 0x8001)).integer(2), 0)
            producer = session.media[17].producer
            session.close()
            session.close()
            self.assertTrue(producer.closed)
            lease.close()

    def test_unsolicited_focus_requests_keyframe_and_loss_releases_input(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = SessionLease('android-auto', directory + '/lock', None)
            lease.acquire()
            transport = FakeTransport()
            released = []
            input_factory = lambda *args: SimpleNamespace(release=lambda: released.append(True), close=lambda: None)
            session = Session(transport, lease, FakeProducer, FakeProducer, input_factory, publish=None)
            session.handle(Packet(0, 6, discovery_payload()))
            session.handle(Packet(17, 8, field(1, 0)))
            session.handle(Packet(17, 0x8003, field(1, 2) + field(2, 12) + field(3, 0)))
            session.handle(Packet(17, 0x8008, field(1, 1) + field(2, 1)))
            session.handle(Packet(17, 0x8008, field(1, 1) + field(2, 1)))
            self.assertEqual(session.media[17].producer.keyframes, 1)
            session.handle(Packet(17, 0x8008, field(1, 2) + field(2, 1)))
            self.assertFalse(session.media[17].producer.enabled)
            self.assertTrue(released)
            session.close()
            lease.close()

    def test_early_video_focus_is_retained_until_channel_and_media_setup(self):
        for mode in (1, 2, 3, 4):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                lease = SessionLease('android-auto', directory + '/lock', None)
                lease.acquire()
                session = Session(FakeTransport(), lease, FakeProducer, FakeProducer,
                    lambda *args: SimpleNamespace(release=lambda: None, close=lambda: None), publish=None)
                session.handle(Packet(0, 6, discovery_payload()))
                session.handle(Packet(17, 0x8008, field(1, mode) + field(2, 1)))
                self.assertNotIn(17, session.media)
                session.handle(Packet(17, 8, field(1, 0)))
                session.handle(Packet(17, 0x8003, field(1, 2) + field(2, 12) + field(3, 0)))
                self.assertEqual(session.media[17].producer.enabled, mode in (1, 4))
                session.close()
                lease.close()

    def test_early_focus_does_not_accept_other_channels_or_invalid_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = SessionLease('android-auto', directory + '/lock', None)
            lease.acquire()
            session = Session(FakeTransport(), lease, FakeProducer, FakeProducer, publish=None)
            session.handle(Packet(0, 6, discovery_payload()))
            for channel, mode in ((29, 1), (77, 1), (17, 9)):
                with self.subTest(channel=channel, mode=mode), self.assertRaises(ValueError):
                    session.handle(Packet(channel, 0x8008, field(1, mode)))
            session.close()
            lease.close()


class ProducerCleanupTests(unittest.TestCase):
    def test_pcm_backlog_preserves_stereo_sample_alignment_after_partial_reads(self):
        producer = AudioProducer.__new__(AudioProducer)
        producer.config = Discovery(discovery_payload()).audio.configs[0]
        producer.stop = threading.Event()
        producer.gain = 1.0
        source = SimpleNamespace(fileno=lambda: 1)
        cancel = threading.Event()
        sample = b'\x01\x02\x03\x04'
        data = sample * 50001 + b'ab'
        chunks = collections.deque(data[offset:offset + 15001] for offset in range(0, len(data), 15001))
        clock = SimpleNamespace(value=0)
        output = []

        def ready(*args):
            if chunks:
                return [source], [], []
            clock.value = .2
            return [], [], []

        def capture(generation, payload, timestamp):
            output.append(payload)
            cancel.set()

        producer.put = capture
        with patch('android_auto.media.time.monotonic', side_effect=lambda: clock.value), \
                patch('android_auto.media.select.select', side_effect=ready), \
                patch('android_auto.media.os.read', side_effect=lambda *args: chunks.popleft()):
            producer.pcm(source, cancel, 1)
        self.assertEqual(output, [sample * 480])

    def test_keyframe_request_invalidates_queued_inter_frames(self):
        producer = VideoProducer.__new__(VideoProducer)
        producer.lock = threading.Lock()
        producer.generation = 1
        producer.queue = queue.Queue(2)
        producer.queue.put((1, None, b'old-inter-frame', 123))
        producer.keyframe = threading.Event()
        producer.request_keyframe()
        self.assertEqual(producer.generation, 2)
        self.assertTrue(producer.queue.empty())
        self.assertTrue(producer.keyframe.is_set())

    def test_video_cleanup_failure_is_reported_and_clears_worker_state(self):
        config = Discovery(discovery_payload()).video.configs[0]
        pipeline = SimpleNamespace(start=lambda **kwargs: None, frames=lambda seconds: iter(()),
                                   close=Mock(side_effect=RuntimeError('display cleanup failed')))
        producer = VideoProducer(config, 1280, 480, 30, factory=lambda *args, **kwargs: pipeline)
        producer.set_enabled(True)
        self.assertTrue(producer.stop.wait(3))
        with self.assertRaisesRegex(RuntimeError, 'display cleanup failed'):
            producer.close()
        self.assertIsNone(producer.pipeline)
        self.assertIsNone(producer.cancel)
        pipeline.close.assert_called_once_with()

    def test_encoder_cleanup_failure_still_stops_capture_and_closes_pipes(self):
        config = Discovery(discovery_payload()).audio.configs[0]
        process = SimpleNamespace(pid=123, stdout=io.BytesIO(), stderr=io.BytesIO(), wait=Mock(return_value=0))

        def make_encoder(source, cancel, gain):
            def frame(**kwargs):
                cancel.set()
                return b'aac'
            return SimpleNamespace(reader=SimpleNamespace(frame=frame),
                                   close=Mock(side_effect=RuntimeError('encoder cleanup failed')))

        with patch('android_auto.media.subprocess.Popen', return_value=process), \
                patch('android_auto.media.os.killpg') as kill_group, \
                patch('carplay_proto.aac.AacCapture', side_effect=make_encoder):
            producer = AudioProducer(2, config)
            producer.set_enabled(True)
            self.assertTrue(producer.stop.wait(3))
            with self.assertRaisesRegex(RuntimeError, 'encoder cleanup failed'):
                producer.close()
        kill_group.assert_called_once_with(123, 15)
        process.wait.assert_called_once_with(timeout=3)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)
        self.assertIsNone(producer.cancel)


class NetworkTests(unittest.TestCase):
    def test_explicit_ipv6_scope_is_retained_for_a_tcp_endpoint(self):
        sock = Mock()
        with patch('android_auto.network.socket.socket', return_value=sock), \
                patch('android_auto.network.socket.if_nametoindex', return_value=7):
            self.assertIs(connect_endpoint('fe80::1%wlan0', 5288), sock)
        sock.connect.assert_called_once_with(('fe80::1', 5288, 0, 7))

    def test_saved_head_unit_uses_current_wpp_password_and_optional_wps_field(self):
        class ServiceObject:
            def __init__(self, *args):
                pass

            def remove_from_connection(self):
                pass

        service_api = SimpleNamespace(Object=ServiceObject, method=lambda *args, **kwargs: lambda function: function)
        dbus_api = SimpleNamespace(service=service_api, String=lambda value, **kwargs: value,
                                   Boolean=lambda value, **kwargs: bool(value), ObjectPath=str,
                                   ByteArray=bytes, Dictionary=lambda value, **kwargs: value,
                                   exceptions=SimpleNamespace(DBusException=RuntimeError))
        properties = {'Favorite': True, 'State': 'idle', 'IPv4.Configuration': {'Method': 'dhcp'},
                      'Ethernet': {'Interface': 'wlan0'}, 'IPv4': {'Address': '192.168.44.2'}}
        target = SimpleNamespace(GetProperties=lambda: properties, SetProperty=Mock(),
                                 Connect=Mock(side_effect=lambda **kwargs: kwargs['reply_handler']()))
        manager = SimpleNamespace(GetTechnologies=lambda: [('/wifi', {'Type': 'wifi', 'Powered': True})],
                                  GetServices=lambda: [('/home', {'Type': 'wifi', 'State': 'ready'}), ('/car', properties)],
                                  RegisterAgent=Mock(), UnregisterAgent=Mock())
        objects = {'/': manager, '/car': target, '/wifi': SimpleNamespace()}
        lease = SimpleNamespace(identity='test', plan_network=Mock(), network_restored=Mock())
        credentials = Credentials(('192.168.44.1', 5288), field(1, 'DiAutoAP') + field(2, 'password8') + field(4, 8))
        with patch.dict('sys.modules', {'dbus': dbus_api, 'dbus.service': service_api}), \
                patch('android_auto.network.network_object', side_effect=lambda bus, name, path: objects[path]), \
                patch('android_auto.network.network_interface', side_effect=lambda obj, name: obj), \
                patch('android_auto.network.find_service', return_value='/car'), \
                patch('android_auto.network.associated_network', return_value=('DiAutoAP', '12:34:56:78:90:ab')), \
                patch('android_auto.network.restore_network') as restore:
            handover = NetworkHandover(lease, None, threading.Event(), log=lambda value: None)
            self.assertEqual(handover.connect(credentials), ('wlan0', '192.168.44.2'))
            self.assertEqual(handover.agent.RequestInput('/car', {'Passphrase': {}, 'WPS': {}}),
                             {'Passphrase': 'password8'})
            handover.close()
        target.SetProperty.assert_called_once_with('Passphrase', 'password8')
        self.assertEqual(restore.call_count, 2)
        manager.UnregisterAgent.assert_called_once_with('/org/sailplay/AndroidAuto/WifiAgent_test')


class EntrypointTests(unittest.TestCase):
    def test_supervisor_selects_both_backends_and_passes_only_supported_options(self):
        supervisor = load_script('projection-service')
        arguments = ['--seconds', '0', '--device', '/org/bluez/hci0/dev_CAR',
                     '--accessory-key', '/private/pin.json', '--sustained']
        commands = supervisor.backend_commands(arguments, 'auto', '/scripts')
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][2:], arguments)
        self.assertEqual(commands[1][2:], ['--seconds', '0', '--device', '/org/bluez/hci0/dev_CAR'])
        self.assertEqual(len(supervisor.backend_commands(arguments, 'carplay', '/scripts')), 1)
        self.assertTrue(supervisor.backend_commands([], 'android-auto', '/scripts')[0][1].endswith('android-auto-phone.py'))

    def test_reconnect_auto_selects_connected_android_auto_and_prefers_dual_carplay(self):
        reconnect = load_script('reconnect-car')
        objects = {'/carplay': {'org.bluez.Device1': {'Paired': True, 'Connected': False, 'UUIDs': [CARPLAY_UUID]}},
                   '/android': {'org.bluez.Device1': {'Paired': True, 'Connected': True, 'UUIDs': [AA_UUID]}}}
        with patch.object(reconnect, 'previous_head_unit', return_value=None), \
                patch.object(reconnect, 'authenticated_head_unit', return_value=False):
            self.assertEqual(reconnect.projection_target(objects, '/carplay', 'auto'), '/android')
            objects['/carplay']['org.bluez.Device1']['Connected'] = True
            objects['/carplay']['org.bluez.Device1']['UUIDs'].append(AA_UUID)
            self.assertEqual(reconnect.projection_target(objects, '/carplay', 'auto'), '/carplay')
            self.assertEqual(reconnect.projection_target(objects, '/carplay', 'android-auto'), '/carplay')

    def test_connection_cleanup_continues_after_session_and_bus_errors(self):
        entry = load_script('android-auto-phone')
        lease = SimpleNamespace(acquire=Mock(), phase=Mock(), close=Mock())
        bus = SimpleNamespace(close=Mock(side_effect=RuntimeError('bus cleanup failed')))
        transport = Mock()
        session = SimpleNamespace(run=Mock(return_value='peer-exit'),
                                  close=Mock(side_effect=RuntimeError('media cleanup failed')))
        power = SimpleNamespace(start=Mock(), close=Mock())
        events = Mock()
        events.attach_mock(transport.handshake, 'handshake')
        events.attach_mock(power.start, 'power')
        worker = entry.Worker(None)
        options = SimpleNamespace(certificate=None, key=None, tcp=['192.168.44.1', '5288'], seconds=1)
        with patch.dict('sys.modules', {'dbus': SimpleNamespace(SystemBus=Mock(return_value=bus))}), \
                patch.object(entry, 'SessionLease', return_value=lease), \
                patch.object(entry, 'restore_network'), patch.object(entry, 'server_context'), \
                patch.object(entry, 'connect_endpoint'), patch.object(entry, 'Transport', return_value=transport), \
                patch.object(entry, 'Session', return_value=session), \
                patch('carplay_proto.mediakeys.MediaKeys') as media_keys, patch('carplay_proto.videodemo.UiCommands'), \
                patch.object(entry, 'ProjectionPower', return_value=power), \
                self.assertLogs(level='ERROR'):
            events.attach_mock(media_keys, 'media_keys')
            entry.run_connection(worker, options)
        self.assertEqual([event[0] for event in events.mock_calls[:3]], ['power', 'handshake', 'media_keys'])
        power.close.assert_called_once_with()
        lease.close.assert_called_once_with()
        self.assertTrue(worker.stop.is_set())
        self.assertEqual(worker.phase, 'idle')


class TlsTests(unittest.TestCase):
    def test_completed_handshake_is_reused_when_media_session_starts(self):
        transport = Transport.__new__(Transport)
        transport.ready = True
        transport.plain = Mock(side_effect=AssertionError('handshake restarted'))
        transport.handshake()
        transport.plain.assert_not_called()

    def test_interrupted_managed_identity_generation_recovers_on_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            server_context(directory=directory)
            certificate = Path(directory) / 'identity.crt'
            key = Path(directory) / 'identity.key'
            original_certificate = certificate.read_bytes()
            key.unlink()
            replace = os.replace

            def interrupted(source, destination):
                if destination == str(certificate):
                    raise OSError('certificate replacement interrupted')
                replace(source, destination)

            with patch('android_auto.transport.os.replace', side_effect=interrupted):
                with self.assertRaisesRegex(OSError, 'replacement interrupted'):
                    server_context(directory=directory)
            self.assertEqual(certificate.read_bytes(), original_certificate)
            server_context(directory=directory)
            public_key = x509.load_pem_x509_certificate(certificate.read_bytes()).public_key()
            private_key = serialization.load_pem_private_key(key.read_bytes(), password=None)
            self.assertEqual(public_key.public_numbers(), private_key.public_key().public_numbers())

    def test_device_libcrypto_generates_a_private_reusable_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            server_context(directory=directory)
            key_path = Path(directory) / 'identity.key'
            certificate_path = Path(directory) / 'identity.crt'
            original_key = key_path.read_bytes()
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
            certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
            key = serialization.load_pem_private_key(original_key, password=None)
            self.assertEqual(certificate.public_key().public_numbers(), key.public_key().public_numbers())
            server_context(directory=directory)
            self.assertEqual(key_path.read_bytes(), original_key)

    def test_phone_tls_server_and_encrypted_fragmented_video(self):
        with tempfile.TemporaryDirectory() as directory:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Sailplay test')])
            now = datetime.datetime.utcnow()
            certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                           .public_key(key.public_key()).serial_number(x509.random_serial_number())
                           .not_valid_before(now - datetime.timedelta(days=1))
                           .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
            certificate_path, key_path = directory + '/certificate', directory + '/key'
            Path(certificate_path).write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            Path(key_path).write_bytes(key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            phone, headunit = socket.socketpair()
            headunit.settimeout(3)
            transport = Transport(phone, server_context(certificate_path, key_path))
            results, errors = [], []

            def peer():
                try:
                    reader = FrameReader()
                    def read_frame():
                        while True:
                            packet = reader.next()
                            if packet is not None:
                                return packet
                            reader.feed(headunit.recv(65536))
                    def send_plain(message_type, payload=b''):
                        headunit.sendall(frame(0, 3, struct.pack('>H', message_type) + payload))
                    send_plain(1, struct.pack('>HH', 1, 2))
                    version = read_frame()
                    self.assertEqual(version.data, b'\x00\x02\x00\x01\x00\x02\x00\x00')
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    context.maximum_version = ssl.TLSVersion.TLSv1_2
                    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
                    tls = context.wrap_bio(incoming, outgoing, server_side=False)
                    while True:
                        try:
                            tls.do_handshake()
                            if outgoing.pending:
                                send_plain(3, outgoing.read())
                            break
                        except ssl.SSLWantReadError:
                            if outgoing.pending:
                                send_plain(3, outgoing.read())
                            packet = read_frame()
                            self.assertEqual(packet.data[:2], b'\x00\x03')
                            incoming.write(packet.data[2:])
                    send_plain(3)  # DiAuto's empty TLS completion envelope.
                    send_plain(4, field(1, 0))
                    assembler = MessageAssembler()
                    while True:
                        packet = read_frame()
                        self.assertTrue(packet.flags & ENCRYPTED)
                        incoming.write(packet.data)
                        plaintext = bytearray()
                        while True:
                            try:
                                plaintext.extend(tls.read(16384))
                            except ssl.SSLWantReadError:
                                break
                        results.append((packet.flags, packet.total))
                        assembled = assembler.add(packet, bytes(plaintext))
                        if assembled is not None:
                            self.assertEqual(assembled, Packet(17, 0, b'x' * 100000))
                            break
                    tls.write(b'\x80\x04' + field(1, 1) + field(2, 1))
                    headunit.sendall(frame(17, 11, outgoing.read()))
                except Exception as error:
                    errors.append(error)
                finally:
                    headunit.close()
            thread = threading.Thread(target=peer)
            thread.start()
            try:
                transport.handshake()
                transport.send(17, 0, b'x' * 100000)
                response = transport.receive(3)
                self.assertEqual(response.type, 0x8004)
                self.assertEqual(Message(response.payload).integer(2), 1)
                thread.join(5)
                self.assertFalse(thread.is_alive())
                if errors:
                    raise errors[0]
                self.assertEqual(results[0], (9, 100002))
                self.assertEqual(results[-1], (10, None))
            finally:
                transport.close()
                headunit.close()
                thread.join(5)


if __name__ == '__main__':
    unittest.main()
