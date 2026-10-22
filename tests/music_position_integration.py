#!/usr/bin/env python3
"""Run on Sailfish as the session user; exercise installed UI without audio.

Uses a temporary MPRIS player and the production progress widget. Never plays,
pauses or seeks the user's actual player. Requires the installed carui binary.
"""
import os
from pathlib import Path
import subprocess
import tempfile


fixture = r'''
    MprisPlayer {
        id: positionProbe
        serviceName: "org.mpris.MediaPlayer2.sailplay_position_probe"
        identity: "Sailplay position test"
        canControl: true; canPlay: true; canPause: true; canSeek: true
        playbackStatus: Mpris.Playing
        Component.onCompleted: position = 73500
        metaData { title: "Position test"; trackId: "/test/track1"; duration: 223000 }
    }
    Timer {
        interval: 1000; repeat: true; running: true
        property int stage: 0
        property string previousKey: ""
        function check(expected, label) {
            var actual = musicProgress.positionSeconds
            if (Math.abs(actual - expected) > 0.05) {
                console.log("POSITION_FAIL", label, actual, expected)
                stop(); Qt.quit(); return false
            }
            console.log("POSITION_OK", label, actual)
            return true
        }
        onTriggered: {
            switch (stage++) {
            case 0:
                lockscreenMusic.mprisController.currentService = positionProbe.serviceName
                musicProgress.refresh()
                break
            case 1:
                if (!check(73.5, "playing")) return
                positionProbe.playbackStatus = Mpris.Paused
                // Metadata is commonly re-emitted together with pause.
                positionProbe.metaData.albumTitle = "Same track, paused"
                musicProgress.refresh()
                break
            case 2:
                if (!check(73.5, "paused after metadata")) return
                console.log("AMBER_PAUSED_CACHE", lockscreenMusic.mprisController.position)
                break
            case 3:
                if (!check(73.5, "paused remains fixed")) return
                positionProbe.position = 0
                musicProgress.refresh()
                break
            case 4:
                if (!check(0, "paused seek to zero")) return
                positionProbe.position = 120000
                musicProgress.refresh()
                break
            case 5:
                if (!check(120, "paused seek forward")) return
                positionProbe.playbackStatus = Mpris.Playing
                positionProbe.position = 121000
                musicProgress.refresh()
                break
            case 6:
                if (!check(121, "resume")) return
                previousKey = musicProgress.trackKey
                positionProbe.metaData.title = "Second track"
                positionProbe.metaData.trackId = "/test/track2"
                positionProbe.position = 0
                musicProgress.refresh()
                break
            case 7:
                if (!check(0, "new track")) return
                carController.playerPositionAvailable(positionProbe.serviceName, previousKey, 999)
                carController.playerPositionAvailable("org.mpris.MediaPlayer2.stale", musicProgress.trackKey, 999)
                if (!check(0, "reject stale replies")) return
                console.log("POSITION_INTEGRATION_PASS")
                stop(); Qt.quit()
            }
        }
    }
    Timer { interval: 15000; running: true; onTriggered: { console.log("POSITION_TIMEOUT"); Qt.quit() } }
'''

source = Path('/opt/sailplay/carui/main.qml').read_text()
source = 'import Amber.Mpris 1.0\nimport "file:///opt/sailplay/carui"\n' + source
source = source.replace('visible: true; width:', 'visible: false; width:', 1)
source = source.replace('carController.restoreShellView()', 'carController.openMusic()', 1)
source = source.replace('source: "WeatherCard.qml"', 'source: "file:///opt/sailplay/carui/WeatherCard.qml"')
source = source[:source.rfind('}')] + fixture + '\n}'
with tempfile.TemporaryDirectory(prefix='sailplay-position-') as directory:
    path = Path(directory) / 'probe.qml'
    path.write_text(source)
    env = dict(os.environ, QT_QPA_PLATFORM='minimal', QT_LOGGING_TO_CONSOLE='1')
    result = subprocess.run(['/opt/sailplay/carui/carui', str(path)], env=env,
                            capture_output=True, text=True, timeout=25)
    output = result.stdout + result.stderr
    print(output)
    assert result.returncode == 0, result.returncode
    assert 'POSITION_INTEGRATION_PASS' in output
    assert 'POSITION_FAIL' not in output and 'POSITION_TIMEOUT' not in output
