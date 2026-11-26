"""Phone-side AAP control, negotiated media, input and session lifecycle."""
import logging
import time

from carplay_proto.displaysettings import load_settings, publish_display
from carplay_proto.vehicletheme import VehicleTheme
from .discovery import Discovery
from .input import InputHandler, SUPPORTED_KEYS
from .media import AudioProducer, MediaChannel, VideoProducer
from .navigation import NavigationBridge
from .protobuf import Message, field


class Session:
    def __init__(self, transport, lease, video_factory=VideoProducer,
                 audio_factory=AudioProducer, input_factory=InputHandler,
                 media_keys=None, commands=None, display_settings=None,
                 publish=publish_display, phone_name='SailfishOS', on_connected=None):
        self.transport, self.lease = transport, lease
        self.video_factory, self.audio_factory = video_factory, audio_factory
        self.input_factory, self.media_keys, self.commands = input_factory, media_keys, commands
        self.display_settings, self.publish = display_settings, publish
        self.phone_name = phone_name
        self.on_connected = on_connected
        self.vehicle_theme = VehicleTheme('android-auto')
        self.discovery = None
        self.early_notifications = []
        self.media = {}
        self.opened = set()
        self.requested = set()
        self.input = None
        self.input_bound = False
        self.navigation = None
        self.mic_open = False
        self.video_focus = self.audio_focus = False
        self.input_focus = False
        self.running = True
        self.exit_reason = None
        self.last_received = time.monotonic()
        self.last_ping = self.last_received
        self.started_at = self.last_received

    def send(self, channel, message_type, payload=b''):
        self.transport.send(channel, message_type, payload)

    def discover(self, payload):
        if self.discovery is not None:
            raise ValueError('duplicate Android Auto service discovery response')
        self.discovery = Discovery(payload)
        night_sensor = next((service for service in self.discovery.services.values()
                             if service.kind == 'sensor' and 10 in service.sensors), None)
        services = (self.discovery.video, self.discovery.audio, self.discovery.input,
                    night_sensor, self.discovery.navigation, self.discovery.microphone)
        for service in services:
            if service is not None:
                self.requested.add(service.id)
                self.send(service.id, 7, field(1, 0) + field(2, service.id))
        logging.info('Android Auto head unit %s video=%d audio=%s input=%s nav=%s mic=%s', self.discovery.name,
                     self.discovery.video.id, self.discovery.audio.id if self.discovery.audio else None,
                     self.discovery.input.id if self.discovery.input else None,
                     self.discovery.navigation.id if self.discovery.navigation else None,
                     self.discovery.microphone.id if self.discovery.microphone else None)
        notifications, self.early_notifications = self.early_notifications, []
        for packet in notifications:
            self.handle(packet)

    def channel_opened(self, channel, payload):
        status = Message(payload).integer(1, signed=True)
        if (channel in self.requested
                and self.discovery.services[channel].kind in ('sensor', 'navigation', 'microphone')
                and status != 0):
            self.requested.discard(channel)
            logging.info('Android Auto %s channel rejected status=%s',
                         self.discovery.services[channel].kind, status)
            return
        if channel not in self.requested or status != 0:
            raise ValueError('head unit rejected Android Auto channel open')
        if channel in self.opened:
            return
        self.opened.add(channel)
        service = self.discovery.services[channel]
        if service.kind == 'sensor':
            self.send(channel, 0x8001, field(1, 10) + field(2, 1000000))
            return
        if service.kind == 'navigation':
            self.navigation = NavigationBridge(channel, service.min_interval_ms)
            return
        if service.kind in ('video', 'audio', 'microphone'):
            self.send(channel, 0x8000, field(1, service.codec))
        elif service.kind == 'input':
            keys = [code for code in SUPPORTED_KEYS if code in service.keys]
            self.send(channel, 0x8002, b''.join(field(1, code) for code in keys))

    def media_configured(self, channel, payload):
        service = self.discovery.services[channel]
        if channel in self.media:
            self.media[channel].configure(payload)
            self.start_media()
            return
        indices = Message(payload).integers(3)
        selected = next((service.configs[index] for index in indices if index in service.configs), None)
        if selected is None:
            raise ValueError('head unit has no mutually supported media configuration')
        if service.kind == 'video':
            display = {'widthPixels': selected.width - selected.margin_width,
                       'heightPixels': selected.height - selected.margin_height,
                       'maxFPS': selected.fps}
            width, height, fps = load_settings(display=display, **(
                {'path': self.display_settings} if self.display_settings else {}))
            producer = self.video_factory(selected, width, height, fps)
        else:
            producer = self.audio_factory(service.codec, selected)
        media = MediaChannel(service, selected, producer)
        self.media[channel] = media
        media.configure(payload)
        logging.info('Android Auto media configured kind=%s channel=%d codec=%d config=%s ackWindow=%d',
                     service.kind, channel, service.codec, selected, media.max_unacked)
        if service.kind == 'video':
            if self.publish is not None:
                self.publish(display)
            if self.discovery.input is not None:
                self.input = self.input_factory(self.discovery.input, selected, width, height, self.media_keys)
        else:
            self.send(0, 18, field(1, 1))
        self.start_media()

    def start_media(self):
        for media in self.media.values():
            focus = self.video_focus if media.service.kind == 'video' else self.audio_focus
            if focus:
                was_started = media.started
                media.start(self.transport)
                if media.service.kind == 'audio' and not was_started and self.media_keys is not None:
                    self.media_keys.started()

    def video_focus_changed(self, payload):
        mode = Message(payload).integer(1)
        if mode not in (1, 2, 3, 4):
            raise ValueError('invalid Android Auto video focus mode')
        self.video_focus, self.input_focus = mode in (1, 4), mode == 1
        logging.info('Android Auto video focus mode=%d video=%s input=%s',
                     mode, self.video_focus, self.input_focus)
        video = self.media.get(self.discovery.video.id)
        if not self.input_focus and self.input is not None:
            self.input.release()
        if video is not None:
            if self.video_focus:
                if video.started:
                    video.producer.request_keyframe()
                else:
                    video.start(self.transport)
            else:
                video.stop(self.transport)

    def audio_focus_changed(self, payload):
        mode = Message(payload).integer(1)
        if mode not in range(1, 8):
            raise ValueError('invalid Android Auto audio focus mode')
        self.audio_focus = mode in (1, 2, 4, 6, 7)
        logging.info('Android Auto audio focus mode=%d active=%s', mode, self.audio_focus)
        if self.discovery.audio is None:
            return
        audio = self.media.get(self.discovery.audio.id)
        if audio is not None:
            audio.producer.gain = .25 if mode == 4 else 1.0
            if self.audio_focus:
                audio.start(self.transport)
                if self.media_keys is not None and not self.media_keys.active:
                    self.media_keys.started()
            else:
                audio.stop(self.transport)

    def handle(self, packet):
        channel, message_type, payload = packet.channel, packet.type, packet.payload
        self.last_received = time.monotonic()
        if message_type == 11:
            timestamp = Message(payload).integer(1)
            if timestamp is None:
                raise ValueError('Android Auto ping timestamp missing')
            self.send(channel, 12, field(1, timestamp))
            return
        if message_type == 12:
            return
        if message_type == 15:
            reason = Message(payload).integer(1)
            self.send(channel, 16)
            self.exit_reason = 'user-exit' if reason in (1, 2) else 'peer-exit'
            self.running = False
            return
        if message_type == 16:
            self.running = False
            return
        if channel == 0:
            if message_type == 6:
                self.discover(payload)
            elif message_type == 19:
                if self.discovery is not None:
                    self.audio_focus_changed(payload)
                elif len(payload) <= 16384 and len(self.early_notifications) < 16:
                    self.early_notifications.append(packet)
                    logging.info('Android Auto deferred audio focus notification')
            elif message_type == 13:
                self.send(0, 14, field(1, 2))
            return
        if self.discovery is None:
            # Surface focus and sensor updates can race the discovery response.
            # Validate their channel identities against discovery before use.
            if (message_type not in (0x8003, 0x8008) or len(payload) > 16384
                    or len(self.early_notifications) >= 16):
                raise ValueError('invalid Android Auto notification before discovery channel={} type={:#x}'.format(
                    channel, message_type))
            self.early_notifications.append(packet)
            logging.info('Android Auto deferred notification channel=%d type=%#x', channel, message_type)
            return
        service = self.discovery.services.get(channel)
        if service is not None and service.kind == 'sensor' and message_type == 0x8003:
            night = Message(payload).messages(10)
            if 10 in service.sensors and night:
                value = night[-1].integer(1)
                if value not in (0, 1):
                    raise ValueError('invalid Android Auto night sensor value')
                self.vehicle_theme.update(bool(value))
            return
        if channel not in self.requested:
            raise ValueError('Android Auto message arrived on an unnegotiated channel={} type={:#x}'.format(
                channel, message_type))
        if message_type == 8:
            self.channel_opened(channel, payload)
            return
        service = self.discovery.services[channel]
        # The receiver's projection surface can announce focus while its
        # channel-open response is still pending. Retain that state for setup.
        if service.kind == 'video' and message_type == 0x8008:
            self.video_focus_changed(payload)
            return
        if channel not in self.opened:
            raise ValueError('Android Auto message arrived before channel open')
        if message_type == 9:
            media = self.media.pop(channel, None)
            if media is not None:
                media.close()
            self.opened.discard(channel)
            self.requested.discard(channel)
            if service.kind == 'video':
                self.exit_reason = 'peer-exit'
                self.running = False
            elif service.kind == 'input':
                self.input_bound = False
                if self.input is not None:
                    self.input.release()
            elif service.kind == 'navigation':
                self.navigation = None
            elif service.kind == 'microphone':
                self.mic_open = False
            return
        if service.kind == 'sensor':
            if message_type == 0x8002:
                logging.info('Android Auto night sensor subscription status=%s', Message(payload).integer(1))
            return
        if service.kind == 'navigation':
            return
        if service.kind == 'microphone':
            if message_type == 0x8003:
                logging.info('Android Auto microphone configured channel=%d', channel)
            elif message_type == 0x8007:
                self.mic_open = bool(Message(payload).integer(1, 0))
                self.send(channel, 0x8008, field(1, 0) + field(2, 1 if self.mic_open else 0))
                logging.info('Android Auto microphone state open=%s', self.mic_open)
            return
        if service.kind == 'input':
            if message_type == 0x8003:
                if Message(payload).integer(1, signed=True) != 0:
                    raise ValueError('head unit rejected Android Auto input binding')
                self.input_bound = True
            elif message_type == 0x8001 and self.input_bound and self.input_focus and self.input is not None:
                self.input.report(payload)
        elif message_type == 0x8003:
            self.media_configured(channel, payload)
        elif message_type == 0x8004 and channel in self.media:
            self.media[channel].acknowledge(payload)
        elif message_type == 0x8002 and channel in self.media:
            media = self.media[channel]
            media.started = False
            media.producer.set_enabled(False)
            media.pending.clear()
            media.sent.clear()

    def return_to_car(self):
        self.exit_reason = 'user-exit'
        self.send(self.discovery.video.id, 0x8007,
                  field(1, self.discovery.video.id) + field(2, 2) + field(3, 2))
        self.send(0, 15, field(1, 1))
        self.running = False

    def run(self, seconds=0):
        self.vehicle_theme.start()
        self.transport.handshake()
        self.send(0, 5, field(4, self.phone_name) + field(5, 'Sailplay'))
        self.started_at = self.last_received = self.last_ping = time.monotonic()
        while self.running:
            now = time.monotonic()
            if seconds and now - self.started_at >= seconds:
                self.send(0, 15, field(1, 1))
                self.exit_reason = 'duration'
                break
            if now - self.last_received > 30:
                raise TimeoutError('Android Auto head unit stopped responding')
            if now - self.started_at > 15 and (
                    self.discovery is None or self.discovery.video.id not in self.media):
                raise TimeoutError('head unit did not configure Android Auto video')
            if now - self.last_ping >= 5:
                self.send(0, 11, field(1, int(now * 1000000000)))
                self.last_ping = now
            if self.commands is not None and self.commands.return_requested() and self.discovery is not None:
                self.return_to_car()
                break
            outgoing = any(media.started and len(media.sent) < media.max_unacked
                           and (media.pending or not media.producer.queue.empty())
                           for media in self.media.values())
            packet = self.transport.receive(0 if outgoing else .02)
            if packet is not None:
                self.handle(packet)
            if not self.running:
                break
            if self.navigation is not None:
                self.navigation.pump(self.transport)
            for media in self.media.values():
                media.pump(self.transport)
                if media.service.kind == 'video' and media.frames_sent and self.lease.state.get('phase') != 'projecting':
                    self.lease.phase('projecting')
                    if self.on_connected is not None:
                        self.on_connected()
                        self.on_connected = None
        return self.exit_reason or 'peer-exit'

    def close(self):
        self.running = False
        if self.navigation is not None:
            self.navigation.close(self.transport)
        errors = []
        for owned in list(self.media.values()) + [self.input, self.media_keys, self.commands, self.transport, self.vehicle_theme]:
            if owned is None:
                continue
            try:
                owned.close()
            except Exception as error:
                errors.append(error)
        self.media.clear()
        self.early_notifications.clear()
        self.input = self.media_keys = self.commands = None
        if errors:
            raise errors[0]
