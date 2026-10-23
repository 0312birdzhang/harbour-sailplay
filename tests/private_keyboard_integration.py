import os,subprocess,time,signal,dbus,socket,shutil
from pathlib import Path
import argparse,tempfile
parser=argparse.ArgumentParser(description='Run as the session user with a bounded CPU lease and no active CarPlay session.')
parser.add_argument('--compositor',default='/opt/sailplay/imira-comp')
parser.add_argument('--server',default='/opt/sailplay/scripts/keyboard-server.py')
parser.add_argument('--qml',default=str(Path(__file__).parent/'fixtures'/'keyboard-input.qml'))
args=parser.parse_args()
root=Path(tempfile.mkdtemp(prefix='sailplay-keyboard-input-'))
shutil.copy(args.qml,root/'input-test.qml')
if Path('/run/user/100000/imira-comp-0').exists():raise SystemExit('Existing compositor; test refused')
bus=dbus.SessionBus();before=bus.get_name_owner('org.maliit.server')
processes=[]
log=(root/'test.log').open('w')
env=dict(os.environ,QT_QPA_PLATFORM='wayland',WAYLAND_DISPLAY='../../display/wayland-0',QT_IM_MODULE='none',MALIIT_DEBUG='1',QT_LOGGING_TO_CONSOLE='1')
def launch(args,e):
 p=subprocess.Popen(args,env=e,stdout=log,stderr=log,start_new_session=True);processes.append(p);return p
def waitfile(path):
 for i in range(80):
  if Path(path).exists():return
  time.sleep(.1)
 raise RuntimeError('not ready: '+path)
try:
 comp=launch([args.compositor,'--width','1920','--height','720','--fps','30'],env)
 waitfile('/run/user/100000/imira-comp-0')
 server=launch(['python3',args.server],env)
 waitfile('/run/user/100000/sailplay-maliit/socket')
 time.sleep(1)
 e=dict(env,WAYLAND_DISPLAY='imira-comp-0',QT_IM_MODULE='Maliit',MALIIT_SERVER_ADDRESS='unix:path=/run/user/100000/sailplay-maliit/socket',CARLIFE_APP_KEY='keyboard-test',QT_DEBUG_PLUGINS='0')
 client=launch(['/usr/bin/qmlscene',str(root/'input-test.qml')],e)
 time.sleep(3)
 sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);sock.settimeout(2)
 def tap(x,y):
  for down in (1,0):sock.sendto(('T %d %d %d'%(down,x,y)).encode(),'/run/user/100000/sailplay-touch.sock');time.sleep(.1)
 tap(400,100)
 time.sleep(6)
 for x,y in ((1318,610),(1407,460),(130,350)):
  tap(x,y);time.sleep(.35)
 time.sleep(1)
 tap(1790,610)
 time.sleep(.5)
 for x,y in ((1318,610),(1407,460),(130,350)):
  tap(x,y);time.sleep(.35)
 tap(400,240)
 time.sleep(1)
 tap(400,100)
 time.sleep(2)
 shutil.copy('/dev/shm/imira-comp-fb',root/'keyboard.fb')
 print('PROCESSES',[p.poll() for p in processes],flush=True)
 print('PHONE_OWNER_UNCHANGED',bus.get_name_owner('org.maliit.server')==before,flush=True)
finally:
 for p in reversed(processes):
  if p.poll() is None:
   os.killpg(p.pid,signal.SIGTERM)
   try:p.wait(timeout=3)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
 log.close()
data=(root/'test.log').read_text(errors='replace')
print('ARTIFACTS',root,flush=True)
assert 'SYNTHETIC_CODEPOINT=20320' in data, 'Chinese candidate was not committed'
assert 'SYNTHETIC_CODEPOINT=0' in data, 'Backspace failed'
assert 'KEYBOARD_VISIBLE=false' in data, 'Hide failed'
assert data.count('KEYBOARD_VISIBLE=true')>=2, 'Reopen failed'
assert bus.get_name_owner('org.maliit.server')==before, 'Phone keyboard owner changed'
print('PRIVATE_KEYBOARD_INPUT_PASS',flush=True)
