"""Live map check: run as the session user with a temporary 1920x720 imira compositor.

Requires the patched Organic Maps and prepared Sailplay viewport QML cache.
Uses a private profile and read-only map links. Verifies saved-route suppression,
full page width, and non-overlapping toolbars in split/full route planning.
"""
import os,time,subprocess,struct,json,hashlib,math,tempfile,re
from pathlib import Path
from urllib.parse import urlencode
root=Path(tempfile.mkdtemp(prefix='sailplay-map-layout57-'))
settings=root/'config/app.organicmaps/organicmaps'; settings.mkdir(parents=True)
# A valid previous route in an isolated profile: projected startup must leave it untouched.
seed=json.dumps([dict(type=0,title='Previous start',x=113.621,y=23.78),dict(type=1,title='Previous finish',x=113.631,y=23.79)])
(settings/'route_points.dat').write_text(seed)
maps=root/'maps';maps.mkdir()
source=Path('/home/defaultuser/.local/share/app.organicmaps/organicmaps')
for version in source.iterdir():
 if version.is_dir() and version.name.isdigit():
  dst=maps/version.name;dst.mkdir()
  for item in version.glob('*.mwm*'):
   if item.is_file() and item.name.endswith(('.mwm','.mwm.routing')): (dst/item.name).symlink_to(item)
env=dict(os.environ,HOME=str(root),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'),
 MWM_WRITABLE_DIR=str(maps),LANG='zh_CN.UTF-8',QT_QPA_PLATFORM='wayland',WAYLAND_DISPLAY='imira-comp-0',
 QML2_IMPORT_PATH='/home/defaultuser/.cache/sailplay/viewport-qml',SAILPLAY_NAVIGATION_EXPORT='1',
 CARLIFE_APP_KEY='b3JnYW5pY21hcHM=',QT_LOGGING_TO_CONSOLE='1')
deadline=time.monotonic()+10
while not Path('/run/user/100000/imira-comp-0').exists():
 if time.monotonic()>deadline:raise RuntimeError('no compositor')
 time.sleep(.1)
logpath=Path('/tmp/sailplay-map-layout57.log')
log=logpath.open('wb')
child=subprocess.Popen(['/usr/bin/organicmaps'],env=env,stdout=log,stderr=log)
record=Path('/run/user/100000/sailplay-app-'+str(child.pid))
try:
 st=Path('/proc/'+str(child.pid)+'/stat').read_text();record.write_text(env['CARLIFE_APP_KEY']+'\n'+st[st.rindex(')')+2:].split()[19]+'\n')
 def command(value):
  with open('/tmp/imira-touch','a') as f:f.write(value+'\n')
 def states():
  result=[]
  for line in logpath.read_text(errors='replace').splitlines():
   if 'SAILPLAY_MAP_LAYOUT ' in line:
    try:result.append(json.loads(line.split('SAILPLAY_MAP_LAYOUT ',1)[1]))
    except ValueError:pass
  return result
 def configured():
  text=(Path(__file__).parent/'comp.log').read_text(errors='replace')
  pairs=re.findall(r'client viewport pid=\d+ screen=(\d+)x(\d+)',text)
  return tuple(map(int,pairs[-1])) if pairs else (0,0)
 def wait_for(predicate):
  deadline=time.monotonic()+20
  while time.monotonic()<deadline:
   if child.poll() is not None:raise RuntimeError('private map startup failed: '+logpath.read_text(errors='replace')[-3000:])
   found=states()
   if found and predicate(found[-1]) and (found[-1]['width'],found[-1]['height'])==configured():return found[-1]
   time.sleep(.2)
  raise AssertionError(states())
 def screenshot(name):
  data=Path('/dev/shm/imira-comp-fb').read_bytes()
  Path('/tmp/sailplay-map-layout57-'+name+'.rgba').write_bytes(data)
 time.sleep(2)
 command('H');time.sleep(.3);command('S Organic Maps')
 first=wait_for(lambda s:s['width']==1780 and not s['routeActive'])
 assert (settings/'route_points.dat').read_text()==seed
 print('PROJECTED_STARTUP_NO_RESTORE_OK',first,flush=True)
 command('D '+env['CARLIFE_APP_KEY']+' -')
 split=wait_for(lambda s:900<s['width']<1500 and not s['routeActive'])
 screenshot('initial')
 url='mapswithme://route?'+urlencode(dict(sll='23.130158,113.621144',saddr='测试起点',dll='23.137,113.632',daddr='测试目的地',type='vehicle'))
 subprocess.run(['/usr/bin/organicmaps',url],env=env,stdout=log,stderr=log,timeout=10,check=True)
 for width,mode in ((split['width'],'split'),(1780,'full')):
  if mode=='full':command('H');time.sleep(.3);command('S Organic Maps')
  state=wait_for(lambda s:s['width']==width and s['routeActive'] and s['routeOpen'] and not s['bottomTools'])
  assert state['routeWidth'] <= width*.43
  time.sleep(4)
  # QML layout can look correct while an activation has enlarged its wl_surface.
  text=(Path(__file__).parent/'comp.log').read_text(errors='replace')
  fits=re.findall(r"content fit 'Organic Maps' surface=(\d+)x(\d+) scale=([0-9.]+)",text)
  assert fits and tuple(map(int,fits[-1][:2]))==configured() and abs(float(fits[-1][2])-1)<.02, fits[-3:]
  screenshot(mode)
  print('PROJECTED_SURFACE_FIT_OK',mode,fits[-1],flush=True)
  print('PROJECTED_PLANNER_LAYOUT_OK',mode,state,flush=True)
 print('PRIVATE_TEST_PROFILE',root,flush=True)
finally:
 child.terminate()
 try:child.wait(5)
 except subprocess.TimeoutExpired:child.kill();child.wait()
 record.unlink(missing_ok=True);log.close()
