"""Bounded H.264/playback producers and Android Auto media flow control."""
import audioop
import collections
import logging
import os
import queue
import select
import signal
import struct
import subprocess
import threading
import time

from carplay_proto.aac import trim_pcm_backlog
from .protobuf import Message, field


def annexb_config(config):
    if len(config) < 7 or config[0] != 1:
        raise ValueError('invalid H.264 AVC configuration')
    offset = 6
    output = bytearray()
    counts = [config[5] & 31]
    for group in range(2):
        if group:
            if offset >= len(config):
                raise ValueError('H.264 PPS count missing')
            counts.append(config[offset])
            offset += 1
        for _ in range(counts[group]):
            if offset + 2 > len(config):
                raise ValueError('H.264 parameter-set length missing')
            size = struct.unpack_from('>H', config, offset)[0]
            offset += 2
            if not size or offset + size > len(config):
                raise ValueError('truncated H.264 parameter set')
            output.extend(b'\x00\x00\x00\x01' + config[offset:offset + size])
            offset += size
    if not all(counts):
        raise ValueError('H.264 SPS and PPS are required')
    return bytes(output)


def clear_queue(pending):
    while True:
        try:
            pending.get_nowait()
        except queue.Empty:
            return


class VideoProducer:
    def __init__(self, config, width, height, fps, factory=None):
        if factory is None:
            from carplay_proto.display import DisplayPipeline
            factory = DisplayPipeline
        self.config, self.width, self.height, self.fps = config, width, height, fps
        self.factory = factory
        self.queue = queue.Queue(2)
        self.enabled, self.stop = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.pipeline = self.cancel = None
        self.generation = 0
        self.error = None
        self.keyframe = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def set_enabled(self, value):
        with self.lock:
            if self.enabled.is_set() == bool(value):
                return
            self.generation += 1
            clear_queue(self.queue)
            if value:
                self.enabled.set()
            else:
                self.enabled.clear()
                if self.cancel is not None:
                    self.cancel.set()

    def request_keyframe(self):
        with self.lock:
            self.generation += 1
            clear_queue(self.queue)
            self.keyframe.set()

    def run(self):
        while not self.stop.is_set():
            if not self.enabled.wait(.1):
                continue
            with self.lock:
                if not self.enabled.is_set() or self.stop.is_set():
                    continue
                generation = self.generation
                cancel = self.cancel = threading.Event()
            pipeline = None
            try:
                pipeline = self.factory(self.width, self.height, self.fps,
                    encoded_width=self.config.width, encoded_height=self.config.height)
                self.pipeline = pipeline
                pipeline.start(stop=cancel)
                need_idr = True
                for config, nals in pipeline.frames(0):
                    if cancel.is_set() or self.stop.is_set():
                        break
                    if self.keyframe.is_set():
                        with self.lock:
                            self.keyframe.clear()
                            generation = self.generation
                        need_idr = True
                        pipeline.request_keyframe()
                    idr = any(nal[0] & 31 == 5 for nal in nals if nal)
                    if need_idr and not idr:
                        continue
                    codec_config = annexb_config(config)
                    frame = b''.join(b'\x00\x00\x00\x01' + nal for nal in nals)
                    if idr:
                        frame = codec_config + frame
                    item = (generation, codec_config, frame, int(time.monotonic() * 1000000))
                    try:
                        self.queue.put_nowait(item)
                        need_idr = False
                    except queue.Full:
                        clear_queue(self.queue)
                        need_idr = True
                        pipeline.request_keyframe()
                        if idr:
                            self.queue.put_nowait(item)
                            need_idr = False
            except Exception as error:
                if not cancel.is_set() and not self.stop.is_set():
                    self.error = error
                    self.stop.set()
            finally:
                try:
                    if pipeline is not None:
                        pipeline.close()
                except Exception as error:
                    self.error = self.error or error
                    self.stop.set()
                finally:
                    with self.lock:
                        self.pipeline = None
                        if self.cancel is cancel:
                            self.cancel = None

    def close(self):
        self.stop.set()
        with self.lock:
            if self.cancel is not None:
                self.cancel.set()
        self.thread.join(10)
        if self.thread.is_alive():
            raise RuntimeError('Android Auto display worker did not stop')
        if self.error is not None:
            raise self.error


def adts_frame(payload):
    size = len(payload) + 7
    if size > 8191:
        raise ValueError('AAC ADTS frame exceeds limit')
    # AAC-LC, 48 kHz, stereo, one raw-data block.
    header = bytes((255, 241, 76, 128 | size >> 11, size >> 3 & 255,
                    (size & 7) << 5 | 31, 252))
    return header + payload


class AudioProducer:
    def __init__(self, codec, config):
        self.codec, self.config = codec, config
        self.queue = queue.Queue(20)
        self.enabled, self.stop = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.cancel = None
        self.generation = 0
        self.gain = 1.0
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def set_enabled(self, value):
        with self.lock:
            if self.enabled.is_set() == bool(value):
                return
            self.generation += 1
            clear_queue(self.queue)
            if value:
                self.enabled.set()
            else:
                self.enabled.clear()
                if self.cancel is not None:
                    self.cancel.set()

    def put(self, generation, payload, timestamp):
        item = (generation, None, payload, timestamp)
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            self.queue.put_nowait(item)

    def pcm(self, source, cancel, generation):
        pending = b''
        tick = None
        startup_deadline = time.monotonic() + 10
        rate_state = None
        timestamp = 0
        samples_sent = 0
        while not cancel.is_set() and not self.stop.is_set():
            now = time.monotonic()
            if tick is None:
                if now >= startup_deadline:
                    raise TimeoutError('Android Auto playback capture produced no PCM')
                delay = .1
            else:
                delay = max(0, tick - now)
            if delay and select.select([source], [], [], min(delay, .1))[0]:
                data = os.read(source.fileno(), 16384)
                if not data:
                    raise EOFError('Android Auto playback capture ended')
                pending, _ = trim_pcm_backlog(pending + data)
                if tick is None:
                    tick = time.monotonic() + .1
                    timestamp = int(tick * 1000000)
                continue
            if tick is None or time.monotonic() < tick:
                continue
            size = min(1920, len(pending) // 4 * 4)
            data, pending = pending[:size] + bytes(1920 - size), pending[size:]
            if self.config.channels == 1:
                data = audioop.tomono(data, 2, .5, .5)
            if self.config.rate != 48000:
                data, rate_state = audioop.ratecv(data, 2, self.config.channels,
                                                 48000, self.config.rate, rate_state)
            if self.gain != 1:
                data = audioop.mul(data, 2, self.gain)
            self.put(generation, data, timestamp + samples_sent * 1000000 // self.config.rate)
            samples_sent += len(data) // (2 * self.config.channels)
            tick += .01
            if tick < time.monotonic() - .1:
                tick = time.monotonic()
                timestamp = int(tick * 1000000)
                samples_sent = 0

    def capture_log(self, process):
        for line in iter(process.stderr.readline, b''):
            logging.info('Android Auto audio capture %s', line.decode('utf-8', errors='replace').rstrip()[:1024])

    def run(self):
        while not self.stop.is_set():
            if not self.enabled.wait(.1):
                continue
            with self.lock:
                if not self.enabled.is_set() or self.stop.is_set():
                    continue
                generation = self.generation
                cancel = self.cancel = threading.Event()
            process = encoder = log_thread = None
            try:
                process = subprocess.Popen(['su', 'defaultuser', '-s', '/bin/sh', '-c',
                    'exec env XDG_RUNTIME_DIR=/run/user/100000 '
                    'python3 /opt/sailplay/scripts/pulse-capture.py'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True)
                log_thread = threading.Thread(target=self.capture_log, args=(process,), daemon=True)
                log_thread.start()
                if self.codec == 1:
                    self.pcm(process.stdout, cancel, generation)
                else:
                    from carplay_proto.aac import AacCapture
                    encoder = AacCapture(process.stdout, cancel, lambda: self.gain)
                    last_data = time.monotonic()
                    timestamp, samples_sent = int(last_data * 1000000), 0
                    while not cancel.is_set() and not self.stop.is_set():
                        try:
                            payload = encoder.reader.frame(timeout=.2)
                        except TimeoutError:
                            if time.monotonic() - last_data > 10:
                                raise
                            continue
                        last_data = time.monotonic()
                        if self.codec == 4:
                            payload = adts_frame(payload)
                        self.put(generation, payload, timestamp + samples_sent * 1000000 // 48000)
                        samples_sent += 1024
            except Exception as error:
                if not cancel.is_set() and not self.stop.is_set():
                    self.error = error
                    self.stop.set()
            finally:
                cancel.set()
                try:
                    if encoder is not None:
                        encoder.close()
                except Exception as error:
                    self.error = self.error or error
                    self.stop.set()
                try:
                    if process is not None:
                        try:
                            try:
                                os.killpg(process.pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                try:
                                    os.killpg(process.pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                                process.wait(timeout=3)
                        finally:
                            try:
                                process.stdout.close()
                            finally:
                                if log_thread is not None:
                                    log_thread.join(1)
                                process.stderr.close()
                except Exception as error:
                    self.error = self.error or error
                    self.stop.set()
                finally:
                    with self.lock:
                        if self.cancel is cancel:
                            self.cancel = None

    def close(self):
        self.stop.set()
        with self.lock:
            if self.cancel is not None:
                self.cancel.set()
        self.thread.join(10)
        if self.thread.is_alive():
            raise RuntimeError('Android Auto audio worker did not stop')
        if self.error is not None:
            raise self.error


class MediaChannel:
    def __init__(self, service, config, producer):
        self.service, self.config, self.producer = service, config, producer
        self.session_id = 0
        self.configured = self.started = False
        self.max_unacked = 1
        self.sent = collections.deque()
        self.pending = collections.deque()
        self.previous_config = None
        self.pending_generation = None
        self.allowed_indices = []
        self.frames_sent = 0
        self.last_acknowledged_at = 0

    def configure(self, payload):
        response = Message(payload)
        if response.integer(1) != 2:
            raise ValueError('head-unit media configuration expected')
        maximum = response.integer(2)
        if maximum is None or not 1 <= maximum <= 4096:
            raise ValueError('invalid Android Auto media ACK window')
        self.max_unacked = min(maximum, 64)
        self.allowed_indices = response.integers(3)
        if self.config.index not in self.allowed_indices:
            raise ValueError('head unit rejected selected media configuration')
        self.configured = True

    def start(self, transport):
        if self.started or not self.configured:
            return
        self.session_id = self.session_id % 0x7fffffff + 1
        transport.send(self.service.id, 0x8001, field(1, self.session_id) + field(2, self.config.index))
        self.sent.clear()
        self.pending.clear()
        self.previous_config = None
        self.last_acknowledged_at = 0
        self.started = True
        self.producer.set_enabled(True)

    def stop(self, transport):
        if self.started:
            transport.send(self.service.id, 0x8002)
        self.started = False
        self.sent.clear()
        self.pending.clear()
        self.producer.set_enabled(False)

    def acknowledge(self, payload):
        message = Message(payload)
        if message.integer(1, signed=True) != self.session_id:
            return
        count = message.integer(2)
        if count is None or count > 4096:
            raise ValueError('invalid Android Auto media acknowledgement')
        if count and self.sent:
            self.last_acknowledged_at = time.monotonic()
        for _ in range(min(count, len(self.sent))):
            self.sent.popleft()

    def pump(self, transport):
        if self.producer.error is not None:
            raise self.producer.error
        if not self.started:
            return False
        if self.sent and time.monotonic() - max(self.sent[0], self.last_acknowledged_at) > 8:
            raise TimeoutError('head unit stopped acknowledging Android Auto {} channel={} unacked={}'.format(
                self.service.kind, self.service.id, len(self.sent)))
        if self.pending_generation != self.producer.generation:
            self.pending.clear()
            self.pending_generation = self.producer.generation
        if not self.pending:
            try:
                generation, config, data, timestamp = self.producer.queue.get_nowait()
            except queue.Empty:
                return False
            if generation != self.producer.generation:
                return False
            if config is not None and config != self.previous_config:
                self.pending.append((1, config))
            self.pending.append((0, struct.pack('>Q', timestamp) + data))
        if len(self.sent) >= self.max_unacked:
            return False
        message_type, payload = self.pending[0]
        transport.send(self.service.id, message_type, payload)
        self.pending.popleft()
        if message_type == 1:
            self.previous_config = payload
        else:
            self.frames_sent += 1
        self.sent.append(time.monotonic())
        return True

    def close(self):
        self.producer.close()
