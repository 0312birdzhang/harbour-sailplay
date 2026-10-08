import configparser

RESOLUTIONS = ((1920, 720), (1600, 600), (1280, 480))


def load_settings(path='/home/defaultuser/.config/sailplay/display.ini'):
    config = configparser.ConfigParser()
    try:
        config.read(path)
        width = config.getint('Display', 'width', fallback=1920)
        height = config.getint('Display', 'height', fallback=720)
        fps = config.getint('Display', 'fps', fallback=30)
        if (width, height) not in RESOLUTIONS or fps not in (30, 60):
            raise ValueError('unsupported projection settings')
        return width, height, fps
    except (ValueError, configparser.Error):
        return 1920, 720, 30
