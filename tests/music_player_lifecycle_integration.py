#!/usr/bin/python3
"""On-device regression for selected MPRIS services disappearing.
Uses silent mock players and private launcher preferences; opening the actual
music entry can activate the stock backend, but never requests playback.
Temporary QML and mock services are removed at process exit.
"""
import sys,atexit
sys.path.insert(0,'/opt/sailplay')
from carplay_proto.projectionpower import ProjectionPower
power=ProjectionPower(phase='connection',maximum_seconds=90);power.start();atexit.register(power.close)
import os,json,subprocess,tempfile,shutil
from pathlib import Path
qml='''import QtQuick 2.0
import Amber.Mpris 1.0
Item {
property var screen
property var fake
property int stage: 0
property int cycles: 0
function find(item,name){if(item.objectName===name)return item;var a=item.children||[];for(var i=0;i<a.length;i++){var f=find(a[i],name);if(f)return f}return null}
Component {id: mock; MprisPlayer {serviceName:"org.mpris.MediaPlayer2.sailplay_lifecycle_test";identity:"Lifecycle test";canControl:true;canPlay:true;canPause:true;playbackStatus:Mpris.Paused;metaData {title:"Test";trackId:"/test/track";duration:100000}}}
Component.onCompleted: {fake=mock.createObject(null);var c=Qt.createComponent("main.qml");screen=c.createObject(null);if(!screen)console.warn("CREATE_ERROR",c.errorString())}
Timer {interval:350;running:true;repeat:true;onTriggered:{
console.warn("LIFECYCLE_STAGE",stage);
var controls=find(screen.contentItem,"musicControls");
switch(stage++) {
case 0:controls.choosePlayer(fake.serviceName);break;
case 1:fake.destroy();break;
case 2:carController.openMusic();break;
case 3:controls.playerMenuOpen=true;break;
case 5:if(++cycles===8){console.warn("LIFECYCLE_SURVIVED",cycles);Qt.quit()}else{fake=mock.createObject(null);stage=0}break;
}
}}
}'''
with tempfile.TemporaryDirectory(prefix='sailplay-queue139-') as d:
 p=Path(d)
 for f in Path('/opt/sailplay/carui').glob('*.qml'):shutil.copyfile(f,p/f.name)
 (p/'MusicPlayer.qml').write_text((p/'MusicPlayer.qml').read_text().replace('carController.ensureMusicBackend()','true'))
 text=(p/'main.qml').read_text().replace('Component.onCompleted: carController.restoreShellView()','Component.onCompleted: {}').replace('visible: true; width:','visible: false; width:',1)
 (p/'main.qml').write_text(text);(p/'mobile-settings.qml').write_text(qml)
 r=p/'runtime';r.mkdir(mode=0o700)
 env=dict(os.environ,HOME=d,XDG_RUNTIME_DIR=str(r),DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/100000/dbus/user_bus_socket',QT_QPA_PLATFORM='minimal',QT_QUICK_BACKEND='software',QT_LOGGING_TO_CONSOLE='1',QT_FORCE_STDERR_LOGGING='1',LANG='en_US.UTF-8')
 out=subprocess.run(['/opt/sailplay/carui/carui',str(p/'mobile-settings.qml'),'1920','720'],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=65)
 print(out.stdout);assert out.returncode == 0 and 'LIFECYCLE_SURVIVED 8' in out.stdout,out.stdout[-5000:]
