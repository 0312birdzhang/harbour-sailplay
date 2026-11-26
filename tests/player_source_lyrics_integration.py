#!/usr/bin/python3
"""Device check of source icons and cached lyrics through the installed UI/helper.

Uses an isolated HOME/database and a silent mock Mconnect MPRIS service. Refuses
to run while the real Mconnect owns either of its services. No playback is sent.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import sys
import atexit

import dbus

sys.path.insert(0, '/opt/sailplay')
from carplay_proto.projectionpower import ProjectionPower
power = ProjectionPower(phase='connection', maximum_seconds=60)
power.start()
atexit.register(power.close)

bus = dbus.SessionBus()
for name in ('org.mpris.MediaPlayer2.harbour_mconnect', 'org.sailfishos.Mconnect.Core'):
    assert not bus.name_has_owner(name), 'Close Mconnect before this isolated check: ' + name

database = Path.home()/'.local/share/harbour-mconnect/mconnect.sqlite'
with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as source:
    song, platform, content = source.execute('select song_id,platform,content from lyrics_cache limit 1').fetchone()
track = '/org/mpris/MediaPlayer2/track/t' + hashlib.sha1((platform+':'+song).encode()).hexdigest()

qml = '''import QtQuick 2.0
import QtQuick.Window 2.2
import Amber.Mpris 1.0
Window {
    visible: false
    width: 1280; height: 720
    property int stage: 0
    property int attempts: 0
    property var fake
    function find(item, name) {
        if (item.objectName === name) return item
        var children = item.children || []
        for (var i=0; i<children.length; ++i) { var result=find(children[i],name); if(result)return result }
        return null
    }
    function fail(message) { console.warn("SOURCE_LYRICS_FAIL", message); Qt.quit() }
    CarPalette { id: testPalette }
    MusicPlayer { id: controls; x: 20; y: 100; width: 540 }
    LyricsPanel {
        id: lyrics; x: 620; y: 90; width: 620; height: 580
        palette: testPalette; player: controls.mprisController; expanded: true
        trackKey: player.currentService + "|" + carController.playerTrackId(player.metaData.trackId)
    }
    Connections { target: carController
        onPlayerLyricsAvailable: console.warn("LYRIC_RESULT", key, rows.length)
    }
    Component { id: mock
        MprisPlayer {
            serviceName: "org.mpris.MediaPlayer2.harbour_mconnect"
            identity: "Silent lyrics regression"; desktopEntry: "harbour-mconnect"
            canControl: true; canPlay: true; canPause: true; playbackStatus: Mpris.Paused
            metaData { title: "Cached lyrics regression"; trackId: TRACK_ID; duration: 300000 }
        }
    }
    Timer { interval: 300; running: true; repeat: true; onTriggered: {
        if (++attempts > 65) { fail("timeout stage=" + stage); return }
        if (stage === 0) {
            var apps = carController.availableApps(true)
            var app = null
            for (var a=0;a<apps.length;++a) if(apps[a].id==="harbour-mconnect-silica")app=apps[a]
            if (!app || !app.icon) { fail("Mconnect desktop alias/icon missing"); return }
            var found=false
            for(var i=0;i<controls.stoppedPlayers.length;++i)
                if(controls.stoppedPlayers[i].id===app.id)found=true
            if(!found) { fail("inactive Mconnect choice missing"); return }
            fake=mock.createObject(null); stage=1; return
        }
        if (stage === 1) {
            if(controls.mprisController.availableServices.indexOf(fake.serviceName)<0)return
            controls.choosePlayer(fake.serviceName); stage=2; return
        }
        if (stage === 2) {
            if(controls.mprisController.desktopEntry!=="harbour-mconnect")return
            var icon=find(controls,"playerSelectorIcon")
            if(!icon || icon.status!==Image.Ready) { fail("selected source icon did not load"); return }
            for(var i=0;i<controls.stoppedPlayers.length;++i)
                if(controls.stoppedPlayers[i].id==="harbour-mconnect-silica") { fail("duplicate Mconnect choice"); return }
            lyrics.load(); stage=3; return
        }
        if (stage === 3) {
            if (attempts % 10 === 0) console.warn("LYRIC_WAIT", lyrics.trackKey, lyrics.loading, lyrics.requested)
            if(!lyrics.lines.length)return
            lyrics.positionSeconds=lyrics.lines[lyrics.lines.length-1][0]+1
            lyrics.update()
            if(lyrics.currentIndex!==lyrics.lines.length-1) { fail("timed lyric selection failed"); return }
            var list=find(lyrics,"timedLyrics")
            if(!list || list.count!==lyrics.lines.length) { fail("lyric model not displayed"); return }
            console.warn("SOURCE_LYRICS_PASS", "icon alias inactive-choice no-duplicate timed-lines",lyrics.lines.length,"current",lyrics.currentIndex)
            fake.destroy(); Qt.quit()
        }
    }}
}'''.replace('TRACK_ID', json.dumps(track))

with tempfile.TemporaryDirectory(prefix='sailplay-source-lyrics-') as directory:
    root = Path(directory)
    cache = root/'.local/share/harbour-mconnect'
    cache.mkdir(parents=True)
    with sqlite3.connect(str(cache/'mconnect.sqlite')) as target:
        target.execute('create table lyrics_cache(song_id text,platform text,content text)')
        target.execute('insert into lyrics_cache values(?,?,?)', (song, platform, content))
    for file in Path('/opt/sailplay/carui').glob('*.qml'):
        shutil.copyfile(file, root/file.name)
    # Avoid activating a real background player from the isolated fixture.
    music = root/'MusicPlayer.qml'
    music.write_text(music.read_text().replace('carController.ensureMusicBackend()', 'true'))
    (root/'probe.qml').write_text(qml)
    runtime = root/'runtime'; runtime.mkdir(mode=0o700)
    env = dict(os.environ, HOME=directory, XDG_RUNTIME_DIR=str(runtime),
               QT_QPA_PLATFORM='minimal', QT_QUICK_BACKEND='software',
               QT_LOGGING_TO_CONSOLE='1', QT_FORCE_STDERR_LOGGING='1', LANG='en_US.UTF-8')
    result = subprocess.run(['/opt/sailplay/carui/carui', str(root/'probe.qml')],
                            env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=30)
    print(result.stdout)
    assert result.returncode == 0 and 'SOURCE_LYRICS_PASS' in result.stdout, 'device UI check failed'
