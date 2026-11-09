"""Translate Android Auto input reports into the private compositor's input."""
import socket

from .protobuf import Message


MEDIA_KEYS = {85: 'PlayPause', 86: 'Pause', 87: 'Next', 88: 'Previous',
              126: 'Play', 127: 'Pause'}
EVDEV_KEYS = {4: 158, 19: 103, 20: 108, 21: 105, 22: 106, 23: 28,
              61: 15, 62: 57, 66: 28, 67: 14}
SUPPORTED_KEYS = sorted(set(MEDIA_KEYS) | set(EVDEV_KEYS))


def letterbox(width, height, canvas_width, canvas_height):
    box_width = width
    box_height = width * canvas_height // canvas_width
    if box_height > height:
        box_height = height
        box_width = height * canvas_width // canvas_height
    box_width &= ~1
    box_height &= ~1
    return ((width - box_width) // 2 & ~1, (height - box_height) // 2 & ~1,
            box_width, box_height)


class InputHandler:
    def __init__(self, service, video, width, height, media=None,
                 path='/run/user/100000/sailplay-touch.sock'):
        self.service, self.media, self.path = service, media, path
        self.width, self.height = width, height
        self.video_width, self.video_height = video.width, video.height
        self.box = letterbox(video.width, video.height, width, height)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.primary = None
        self.x = self.y = 0
        self.pressed_keys = set()

    def send(self, command):
        try:
            self.sock.sendto(command.encode('ascii'), self.path)
        except (FileNotFoundError, ConnectionRefusedError, BlockingIOError):
            # Input is confined to this display even while its surface restarts.
            pass

    def point(self, pointer):
        x, y = pointer.integer(1), pointer.integer(2)
        if x is None or y is None or x > 0xffffffff or y > 0xffffffff:
            raise ValueError('Android Auto touch coordinates missing')
        source_width = self.service.touch_width or self.video_width
        source_height = self.service.touch_height or self.video_height
        x = min(source_width - 1, x) * self.video_width // source_width
        y = min(source_height - 1, y) * self.video_height // source_height
        left, top, box_width, box_height = self.box
        self.x = max(0, min(self.width - 1, (x - left) * self.width // box_width))
        self.y = max(0, min(self.height - 1, (y - top) * self.height // box_height))

    def report(self, payload):
        report = Message(payload)
        if report.integer(1) is None:
            raise ValueError('Android Auto input timestamp missing')
        if report.blob(3) is not None:
            self.touch(Message(report.blob(3)))
        if report.blob(4) is not None:
            for key in Message(report.blob(4)).messages(1):
                self.key(key.integer(1), key.integer(2))

    def touch(self, event):
        action = event.integer(3)
        pointers = event.messages(1)
        index = event.integer(2, 0)
        if action not in range(7) or len(pointers) > 16:
            raise ValueError('invalid Android Auto touch action')
        if action in (1, 3, 4):
            self.release_touch()
            return
        if action in (0, 5, 6) and index >= len(pointers):
            raise ValueError('invalid Android Auto touch action index')
        if action == 0:
            self.release_touch()
            self.primary = pointers[index].integer(3)
            if self.primary is None:
                raise ValueError('Android Auto pointer identity missing')
        if action == 6 and pointers[index].integer(3) == self.primary:
            self.release_touch()
            return
        pointer = next((point for point in pointers if point.integer(3) == self.primary), None)
        if self.primary is not None and pointer is not None:
            self.point(pointer)
            self.send('T 1 {} {}'.format(self.x, self.y))

    def key(self, code, down):
        if down not in (0, 1) or code is None:
            raise ValueError('invalid Android Auto key event')
        if code not in SUPPORTED_KEYS:
            return
        if code in MEDIA_KEYS:
            if down and code not in self.pressed_keys and self.media is not None:
                import queue
                try:
                    self.media.pending.put_nowait(MEDIA_KEYS[code])
                except queue.Full:
                    pass
        elif code in EVDEV_KEYS:
            self.send('K {} {}'.format(down, EVDEV_KEYS[code]))
        if down:
            self.pressed_keys.add(code)
        else:
            self.pressed_keys.discard(code)

    def release_touch(self):
        if self.primary is not None:
            self.send('T 0 {} {}'.format(self.x, self.y))
            self.primary = None

    def release(self):
        self.release_touch()
        for code in self.pressed_keys:
            if code in EVDEV_KEYS:
                self.send('K 0 {}'.format(EVDEV_KEYS[code]))
        self.pressed_keys.clear()

    def close(self):
        self.release()
        self.sock.close()
