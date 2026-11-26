#!/usr/bin/env python3
"""Host Qt test of the production MusicPlayer selection timers with mock services."""
from pathlib import Path
import os
import shutil
import subprocess
import shlex
import tempfile

root = Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory(prefix='sailplay-music-selection-') as directory:
    temp = Path(directory)
    for name in ['MusicPlayer.qml', 'CarPalette.qml', 'ContentPage.qml', 'ContentPane.qml']:
        shutil.copyfile(root / 'display-source/carui' / name, temp / name)
    silica = temp / 'Sailfish/Silica'
    amber = temp / 'Amber/Mpris'
    silica.mkdir(parents=True, exist_ok=True)
    amber.mkdir(parents=True, exist_ok=True)
    (silica / 'qmldir').write_text('module Sailfish.Silica\nIconButton 1.0 IconButton.qml\nIcon 1.0 Icon.qml\nGlassItem 1.0 GlassItem.qml\n')
    (silica / 'GlassItem.qml').write_text('import QtQuick 2.0\nItem { property color color; property real falloffRadius; property real radius; property bool cache }\n')
    (silica / 'Icon.qml').write_text('import QtQuick 2.0\nItem { property color color; property string source }\n')
    (silica / 'IconButton.qml').write_text('''import QtQuick 2.0
    Item { property Icon icon: Icon {} signal clicked() }
    ''')
    (amber / 'qmldir').write_text('module Amber.Mpris\nMprisController 1.0 MprisController.qml\nsingleton Mpris 1.0 Mpris.qml\n')
    (amber / 'Mpris.qml').write_text('pragma Singleton\nimport QtQuick 2.0\nQtObject { enum Playback { Stopped, Playing, Paused } }\n')
    (amber / 'MprisController.qml').write_text('''import QtQuick 2.0
    QtObject {
     property bool singleService: true
     property string currentService: "org.mpris.MediaPlayer2.b"
     property var availableServices: ["org.mpris.MediaPlayer2.b"]
     property var availableClients: []
     property int playbackStatus: 2
     property bool canPlay: true
     property bool canPause: true
     property bool canGoNext: true
     property bool canGoPrevious: true
     property string identity: "B"
     property string desktopEntry: "b"
     property var metaData: ({title:"Track",contributingArtist:"Artist",albumTitle:"Album"})
     function pause() {} function next() {} function previous() {}
    }
    ''')
    (temp / 'probe.qml').write_text('''import QtQuick 2.0
    Item {
     width: 1200; height: 720
     QtObject {
      id: carController
      property bool dayTheme: false
      property bool aReady: false
      property bool hasRememberedMusic: true
      property string lastMusicApp: "b"
      property string lastMusicName: "B"
      property string musicError: ""
      signal musicAppRequested(string appId)
      signal playerPlaybackFinished(string service, bool success)
      function availableApps(all) { return [] }
      function ensureMusicBackend(app) { return true }
      function musicAppIcon(app) { return "" }
      function musicServiceForApp(app, services) { return app === "a" && !aReady ? "" : "org.mpris.MediaPlayer2."+app }
      function preferredMusicService(services) { return "org.mpris.MediaPlayer2.b" }
      function rememberMusicPlayer(service) {}
      function playMusicPlayer(service) {}
     }
     MusicPlayer { id: music; width: 1000 }
     Timer {
      interval: 300; repeat: true; running: true
      property int stage: 0
      onTriggered: {
       if (stage > 0 && (music.mprisController.currentService !== "org.mpris.MediaPlayer2.b" || music.pendingApp !== "")) {
        console.log("MUSIC_SELECTION_FAIL", stage, music.mprisController.currentService, music.pendingApp)
        Qt.quit(); return
       }
       if (stage === 3) { console.log("MUSIC_SELECTION_PASS current other-running menu"); Qt.quit(); return }
       carController.aReady = false
       if (stage === 1) music.mprisController.currentService = "org.mpris.MediaPlayer2.c"
       carController.musicAppRequested("a")
       if (stage === 2) music.choosePlayer("org.mpris.MediaPlayer2.b", true)
       else carController.musicAppRequested("b")
       carController.aReady = true
       stage++
      }
     }
    }
    ''')
    (temp / 'runner.cpp').write_text('''#include <QGuiApplication>
    #include <QQmlApplicationEngine>
    #include <QUrl>
    int main(int argc,char **argv) {
     QGuiApplication app(argc,argv); QQmlApplicationEngine engine;
     QObject::connect(&engine,&QQmlEngine::quit,&app,&QCoreApplication::quit);
     engine.load(QUrl::fromLocalFile(QString::fromLocal8Bit(argv[1])));
     if(engine.rootObjects().isEmpty())return 1;
     return app.exec();
    }
    ''')
    flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','Qt5Quick','Qt5Qml'],text=True))
    subprocess.run(['g++','-fPIC',str(temp/'runner.cpp'),'-o',str(temp/'runner'),*flags],check=True)
    result = subprocess.run([str(temp/'runner'),str(temp/'probe.qml')],env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QML2_IMPORT_PATH=str(temp)),text=True,capture_output=True,timeout=15)
    output=result.stdout+result.stderr
    print(output)
    assert result.returncode==0
    assert 'MUSIC_SELECTION_PASS' in output
    assert 'MUSIC_SELECTION_FAIL' not in output
    assert not any(error in output for error in ('ReferenceError', 'TypeError', 'Cannot assign', 'is not a type'))
    shutil.copyfile(root / 'tests/content_controls_integration.qml', temp / 'content.qml')
    result = subprocess.run([str(temp/'runner'),str(temp/'content.qml')],env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QML2_IMPORT_PATH=str(temp)),text=True,capture_output=True,timeout=15)
    output = result.stdout + result.stderr
    print(output)
    assert result.returncode == 0 and 'CONTENT_CONTROLS_PASS' in output
    assert 'CONTENT_CONTROLS_FAIL' not in output
    assert not any(error in output for error in ('ReferenceError', 'TypeError', 'Cannot assign', 'is not a type'))
