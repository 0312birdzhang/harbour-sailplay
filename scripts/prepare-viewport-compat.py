#!/usr/bin/python3
"""Use live window dimensions for projected Silica pages, without system edits."""
from pathlib import Path
import os


def adapt(text):
    changes = {
        'readonly property real _screenWidth: stack.verticalOrientation ? Screen.width : Screen.height':
        'readonly property real _screenWidth: stack.verticalOrientation ? _sailplayPortraitWidth : _sailplayPortraitHeight',
        'readonly property real _screenHeight: stack.verticalOrientation ? Screen.height : Screen.width':
        'readonly property real _screenHeight: stack.verticalOrientation ? _sailplayPortraitHeight : _sailplayPortraitWidth',
        'width: Screen.width': 'width: window._sailplayPortraitWidth',
        'height: Screen.height': 'height: window._sailplayPortraitHeight',
    }
    if any(text.count(old)!=1 for old in changes) or text.count('id: window')!=1:
        raise RuntimeError('unsupported Silica ApplicationWindow source; viewport override not applied')
    for old,new in changes.items():text=text.replace(old,new)
    return text.replace('id: window', 'id: window\n    readonly property real _sailplayPortraitWidth: __quickWindow ? Math.min(__quickWindow.width, __quickWindow.height) : Screen.width\n    readonly property real _sailplayPortraitHeight: __quickWindow ? Math.max(__quickWindow.width, __quickWindow.height) : Screen.height',1)


def prepare():
    source=Path('/usr/lib64/qt5/qml/Sailfish/Silica')
    target=Path.home()/'.cache/sailplay/viewport-qml/Sailfish/Silica'
    text=adapt((source/'ApplicationWindow.qml').read_text())
    target.mkdir(parents=True,exist_ok=True)
    for item in source.iterdir():
        if item.name=='ApplicationWindow.qml':continue
        link=target/item.name
        if not os.path.lexists(str(link)):link.symlink_to(item)
    temporary=target/'ApplicationWindow.qml.tmp'
    temporary.write_text(text)
    temporary.replace(target/'ApplicationWindow.qml')
    print('Sailplay projected Silica viewport compatibility ready',flush=True)


if __name__=='__main__':prepare()
