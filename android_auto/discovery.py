"""Select channels and configurations from the head unit's service discovery."""
import collections

from .protobuf import Message


RESOLUTIONS = {1: (800, 480), 2: (1280, 720), 3: (1920, 1080),
               4: (2560, 1440), 5: (3840, 2160), 6: (720, 1280),
               7: (1080, 1920), 8: (1440, 2560), 9: (2160, 3840)}
VideoConfig = collections.namedtuple('VideoConfig', 'index width height fps margin_width margin_height')
AudioConfig = collections.namedtuple('AudioConfig', 'index rate bits channels')


class Service:
    def __init__(self, message):
        self.id = message.integer(1)
        if self.id is None or not 1 <= self.id <= 255:
            raise ValueError('invalid Android Auto service channel')
        self.message = message
        self.kind = None
        self.codec = None
        self.configs = {}
        self.keys = []
        self.touch_width = self.touch_height = None
        if message.blob(3) is not None:
            self.sink(Message(message.blob(3)))
        elif message.blob(4) is not None:
            self.kind = 'input'
            source = Message(message.blob(4))
            self.keys = source.integers(1)
            if source.blob(2) is not None:
                touch = Message(source.blob(2))
                self.touch_width, self.touch_height = touch.integer(1), touch.integer(2)
                if not self.touch_width or not self.touch_height or max(self.touch_width, self.touch_height) > 16384:
                    raise ValueError('invalid Android Auto touchscreen dimensions')
        elif message.blob(2) is not None:
            self.kind = 'sensor'
            self.sensors = [sensor.integer(1) for sensor in Message(message.blob(2)).messages(1)]

    def sink(self, sink):
        self.codec = sink.integer(1)
        self.audio_type = sink.integer(2, 0)
        if self.codec == 3:
            self.kind = 'video'
            for index, config in enumerate(sink.messages(4)):
                resolution, frame_rate = config.integer(1), config.integer(2)
                codec = config.integer(10, self.codec)
                if resolution not in RESOLUTIONS or frame_rate not in (1, 2) or codec != 3:
                    continue
                width, height = RESOLUTIONS[resolution]
                margin_width, margin_height = config.integer(3, 0), config.integer(4, 0)
                if (margin_width % 2 or margin_height % 2 or width - margin_width < 320
                        or height - margin_height < 240):
                    continue
                self.configs[index] = VideoConfig(index, width, height, 60 if frame_rate == 1 else 30,
                                                 margin_width, margin_height)
        elif self.codec in (1, 2, 4) and self.audio_type == 3:
            self.kind = 'audio'
            for index, config in enumerate(sink.messages(3)):
                rate, bits, channels = config.integer(1), config.integer(2), config.integer(3)
                if bits != 16 or channels not in (1, 2) or rate not in (8000, 16000, 24000, 32000, 44100, 48000):
                    continue
                # The existing AAC capture encoder has a 48 kHz stereo clock.
                if self.codec != 1 and (rate, channels) != (48000, 2):
                    continue
                self.configs[index] = AudioConfig(index, rate, bits, channels)


class Discovery:
    def __init__(self, payload):
        message = Message(payload)
        self.name = message.text(14) or message.text(8) or message.text(3)
        self.services = {}
        for descriptor in message.messages(1):
            service = Service(descriptor)
            if service.id in self.services:
                raise ValueError('duplicate Android Auto service channel')
            self.services[service.id] = service
        self.video = self.choose('video')
        self.audio = self.choose('audio', required=False)
        self.input = self.choose('input', required=False)
        self.sensor = self.choose('sensor', required=False)
        if self.input is not None:
            # DiAuto 0.3.12 advertises full video dimensions but reports touches
            # relative to the UI after removing the negotiated video margins.
            self.input.touch_content_coordinates = self.name == 'DiAuto'

    def choose(self, kind, required=True):
        candidates = [service for service in self.services.values() if service.kind == kind
                      and (kind not in ('video', 'audio') or service.configs)]
        if not candidates:
            if required:
                raise ValueError('head unit has no compatible H.264 video configuration')
            return None
        return sorted(candidates, key=lambda service: service.id)[0]
