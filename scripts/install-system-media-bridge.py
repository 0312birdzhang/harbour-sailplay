#!/usr/bin/python3
"""Attach a reversible queue adapter to the stock media application's QML."""
import hashlib
import json
import os
from pathlib import Path
import sys

BLOCK='''    // BEGIN SAILPLAY QUEUE BRIDGE
    Loader { source: Qt.resolvedUrl("SailplayQueueBridge.qml") }
    // END SAILPLAY QUEUE BRIDGE
'''

def update(target, state, restore=False):
    if not target.is_file():return 'not-installed'
    data=target.read_bytes()
    text=data.decode('utf-8')
    if restore:
        if BLOCK not in text:return 'unchanged'
        result=text.replace(BLOCK,'',1).encode('utf-8')
    else:
        if BLOCK in text:return 'unchanged'
        if 'SAILPLAY QUEUE BRIDGE' in text:raise ValueError('unrecognized existing queue bridge')
        anchor='    id: app\n'
        if 'ApplicationWindow {' not in text or text.count(anchor)!=1:
            raise ValueError('unrecognized stock media source')
        state.mkdir(parents=True,exist_ok=True)
        (state/'mediaplayer.qml.original').write_bytes(data)
        (state/'identity.json').write_text(json.dumps({'originalSha256':hashlib.sha256(data).hexdigest()}))
        result=text.replace(anchor,anchor+BLOCK,1).encode('utf-8')
    temporary=target.with_name(target.name+'.sailplay-tmp')
    created=False
    try:
        with temporary.open('xb') as output:
            created=True;output.write(result);output.flush();os.fsync(output.fileno())
        os.chmod(temporary,target.stat().st_mode & 0o777)
        os.replace(str(temporary),str(target))
    finally:
        if created and temporary.exists():temporary.unlink()
    return 'restored' if restore else 'installed'

if __name__=='__main__':
    print(update(Path('/usr/share/jolla-mediaplayer/mediaplayer.qml'),
                 Path('/var/lib/sailplay/system-media'), '--restore' in sys.argv))
