import configparser
import os
import tempfile

RESOLUTIONS = ((1920, 720), (1600, 600), (1280, 480))


def display_modes(display):
    width, height = int(display['widthPixels']), int(display['heightPixels'])
    if not (320 <= width <= 7680 and 240 <= height <= 4320) or width % 2 or height % 2:
        raise ValueError('invalid head-unit display dimensions')
    # These are encoder scaling choices, not advertised decoder modes.
    return tuple((width * n // 6 // 2 * 2, height * n // 6 // 2 * 2) for n in (6, 5, 4))


def publish_display(display, path='/run/sailplay-display.ini'):
    modes = display_modes(display)
    maximum = max(1, min(60, int(display.get('maxFPS', 30))))
    fd, temporary = tempfile.mkstemp(prefix='.sailplay-display-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write('[Display]\nwidth={}\nheight={}\nmaxFPS={}\n'.format(*modes[0], maximum))
            os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_settings(path='/home/defaultuser/.config/sailplay/display.ini', display=None):
    modes = display_modes(display) if display is not None else RESOLUTIONS
    maximum = max(1, min(60, int(display.get('maxFPS', 30)))) if display is not None else 60
    config = configparser.ConfigParser()
    try:
        config.read(path)
        width = config.getint('Display', 'width', fallback=modes[0][0])
        height = config.getint('Display', 'height', fallback=modes[0][1])
        fps = config.getint('Display', 'fps', fallback=30)
        if display is not None:
            index = config.getint('Display', 'resolutionIndex', fallback=0)
            width, height = modes[index] if 0 <= index < len(modes) else modes[0]
        if (width, height) not in modes or fps not in (30, 60):
            raise ValueError('unsupported projection settings')
        return width, height, min(fps, maximum)
    except (ValueError, configparser.Error):
        return *modes[0], min(30, maximum)
