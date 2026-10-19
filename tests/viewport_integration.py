"""Live compositor check: needs /tmp/sailplay-viewport-probe and its QML.

Run /opt/sailplay/scripts/prepare-viewport-compat.py first.
Cross-build viewport_probe.cpp with Qt5Quick and sailfishapp, copy it and viewport_probe.qml
as /tmp/sailplay-viewport-probe{,.qml}, then run this as the session user.
Temporarily changes the projected layout and restores it in finally.
"""
import os,time,json,subprocess,struct,math
from pathlib import Path
commands=Path('/tmp/imira-touch')
lines=commands.read_text().splitlines() if commands.exists() else []
layout='H';shown=''
for line in lines:
 if line=='H' or line.startswith('H '):layout='H';shown=''
 elif line.startswith('D '):layout=line;shown=''
 elif line.startswith('S '):shown=line
restore=layout+'\n'+(shown+'\n' if shown else '')
deadline=time.monotonic()+30
while not Path('/dev/shm/imira-comp-fb').exists() or not Path('/run/user/100000/imira-comp-0').exists():
 if time.monotonic()>deadline:raise RuntimeError('projected compositor is not running')
 time.sleep(.2)
_,_,width,height=struct.unpack('<4I',Path('/dev/shm/imira-comp-fb').read_bytes()[:16])
print('OUTPUT_RESOLUTION',width,height,flush=True)
scale=width/1920
full_width=width-math.floor(140*scale+.5)
map_width=math.floor((full_width-48*scale)*.65+.5)
map_height=math.floor(height*(1-32/720)+.5)
key='c2FpbHBsYXktZ2VvbWV0cnktcHJvYmU='
def command(text):
 with commands.open('a') as f:f.write(text+'\n')
observed=Path('/tmp/sailplay-viewport-observed.json')
if observed.exists():observed.unlink()
env=dict(os.environ,QML2_IMPORT_PATH=os.path.expanduser('~/.cache/sailplay/viewport-qml'),QT_QPA_PLATFORM='wayland',WAYLAND_DISPLAY='imira-comp-0',XDG_RUNTIME_DIR='/run/user/100000',CARLIFE_APP_KEY=key)
child=None
try:
 deadline=time.monotonic()+20
 while not Path('/run/user/100000/imira-comp-0').exists():
  if time.monotonic()>deadline:raise RuntimeError('projected compositor is not running')
  time.sleep(.2)
 command('D '+key+' -')
 time.sleep(.3)
 child=subprocess.Popen(['/tmp/sailplay-viewport-probe'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 def wait_size(width,height):
  deadline=time.monotonic()+8;state={}
  while time.monotonic()<deadline:
   try:state=json.loads(observed.read_text())
   except (FileNotFoundError,ValueError):pass
   if all(state.get(k)==v for k,v in dict(width=width,height=height,screenWidth=width,screenHeight=height).items()) and width*.8 <= state.get("pageWidth",0) <= width and height*.8 <= state.get("pageHeight",0) <= height:
    print('VIEWPORT_OK',state,flush=True);return
   if child.poll() is not None:raise RuntimeError(child.stderr.read().decode())
   time.sleep(.15)
  raise AssertionError(state)
 wait_size(map_width,map_height)  # First configure may precede shell role creation.
 for cycle in range(5):
  command('H');time.sleep(.3)
  wait_size(map_width,map_height)  # Hidden maps keep their viewport.
  command('S '+key);wait_size(full_width,height)
  command('D '+key+' -');wait_size(map_width,map_height)
  command('D '+key+' -');wait_size(map_width,map_height)
  print('VIEWPORT_CYCLE_OK',cycle+1,flush=True)
 print('VIEWPORT_ROUNDTRIP_OK',flush=True)
finally:
 if child and child.poll() is None:child.terminate();child.wait(3)
 command(restore.rstrip())
