#!/usr/bin/python3
"""Keep Jolla media remote controls available when its panel is hidden.

Only Sailplay-launched players use this private QML import tree. System files
remain untouched; unknown source versions fall back to the original module.
"""
from pathlib import Path
import os


def prepare():
    source = Path('/usr/lib64/qt5/qml/com/jolla/mediaplayer')
    target = Path.home() / '.cache/sailplay/qml/com/jolla/mediaplayer'
    text = (source / 'AudioPlayer.qml').read_text()
    changes = {
        'property var localMetadata: playerVisible ? player.metadata : null':
            'property var localMetadata: active ? player.metadata : null',
        'if (!active || !playerVisible)': 'if (!active)',
    }
    if (text.count(next(iter(changes))) != 1
            or text.count('if (!active || !playerVisible)') != 2):
        raise RuntimeError('unsupported Jolla AudioPlayer source; compatibility override not applied')
    for old, new in changes.items():
        text = text.replace(old, new)
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name == 'AudioPlayer.qml':
            continue
        link = target / item.name
        if not os.path.lexists(str(link)):
            link.symlink_to(item)
    temporary = target / 'AudioPlayer.qml.tmp'
    temporary.write_text(text)
    temporary.replace(target / 'AudioPlayer.qml')
    print('Sailplay Jolla media remote-control compatibility ready', flush=True)


if __name__ == '__main__':
    prepare()
