"""Phone-side AAP control, negotiated media, input and session lifecycle."""
import logging
import time

from carplay_proto.displaysettings import load_settings, publish_display
from .discovery import Discovery
from .input import InputHandler, SUPPORTED_KEYS
from .media import AudioProducer, MediaChannel, VideoProducer
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
        self.discovery = None
        self.early_notifications = []
        self.media = {}
        self.opened = set()
        self.requested = set()
        self.input = None
        self.input_bound = False
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
        services = (self.discovery.video, self.discovery.audio, self.discovery.input)
        for service in services:
            if service is not None:
                self.requested.add(service.id)
                self.send(service.id, 7, field(1, 0) + field(2, service.id))
        logging.info('Android Auto head unit %s video=%d audio=%s input=%s', self.discovery.name,
                     self.discovery.video.id, self.discovery.audio.id if self.discovery.audio else None,
                     self.discovery.input.id if self.discovery.input else None)
        notifications, self.early_notifications = self.early_notifications, []
        for packet in notifications:
            self.handle(packet)

    def channel_opened(self, channel, payload):
        if channel not in self.requested or Message(payload).integer(1, signed=True) != 0:
            raise ValueError('head unit rejected Android Auto channel open')
        if channel in self.opened:
            return
        self.opened.add(channel)
        service = self.discovery.services[channel]
        if service.kind in ('video', 'audio'):
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
            elif message_type == 19 and self.discovery is not None:
                self.audio_focus_changed(payload)
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
            # Navigation uses the phone's location and night-mode providers.
            # Unsolicited receiver sensor batches do not change those providers.
            Message(payload)
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
            if service.kind == 'video':
                self.exit_reason = 'peer-exit'
                self.running = False
            elif service.kind == 'input':
                self.input_bound = False
                if self.input is not None:
                    self.input.release()
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
            packet = self.transport.receive(.001 if outgoing else .02)
            if packet is not None:
                self.handle(packet)
            if not self.running:
                break
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
        errors = []
        for owned in list(self.media.values()) + [self.input, self.media_keys, self.commands, self.transport]:
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
