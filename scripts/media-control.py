#!/usr/bin/env python3
"""Operate the existing phone MPRIS player, without launching an app."""
import os
import sys
import subprocess
import configparser
from pathlib import Path
import json
import time

def is_local_player(bus, name):
    try:
        pid = int(bus.call_blocking('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                   'org.freedesktop.DBus', 'GetConnectionUnixProcessID',
                                   's', (str(name),), timeout=1))
        return Path(os.readlink('/proc/%d/exe' % pid)).name != 'mpris-proxy'
    except (OSError, TypeError, ValueError):
        return True
    except Exception:
        # A player may disappear between enumeration and the PID lookup.
        return False

def exclusive_play(bus,interface,target,perform):
    paused=[]
    try:
        for name in bus.list_names():
            if not str(name).startswith('org.mpris.MediaPlayer2.') or str(name)==target:continue
            if not is_local_player(bus, name):continue
            obj=bus.get_object(name,'/org/mpris/MediaPlayer2')
            props=interface(obj,'org.freedesktop.DBus.Properties').GetAll('org.mpris.MediaPlayer2.Player',timeout=2)
            if str(props.get('PlaybackStatus'))=='Playing' and props.get('CanPause',False):
                interface(obj,'org.mpris.MediaPlayer2.Player').Pause(timeout=2)
                paused.append(obj)
        return perform()
    except Exception:
        for obj in paused:
            try:interface(obj,'org.mpris.MediaPlayer2.Player').Play(timeout=2)
            except Exception:pass
        raise

def system_play(bus,interface,uri=''):
    api=interface(bus.get_object('com.jolla.mediaplayer','/com/jolla/mediaplayer/sailplay'),'com.jolla.mediaplayer.sailplay')
    deadline=time.monotonic()+2.5
    while True:
        state=json.loads(str(api.snapshot(timeout=2)))
        if state.get('ready'):break
        if time.monotonic()>=deadline:raise RuntimeError('system media queue not ready')
        time.sleep(.1)
    rows=state.get('items',[])
    if not rows:raise RuntimeError('empty system media library')
    index=next((i for i,row in enumerate(rows) if uri and row.get('uri')==uri),int(state.get('index',-1)))
    index=max(0,index)
    if not api.playIndex(index,signature='i',timeout=2):raise RuntimeError('system media queue unavailable')

def remembered_player():
    settings=configparser.ConfigParser(interpolation=None)
    try:
        settings.read(str(Path.home()/'.config/sailplay/ui-state.ini'))
        return (settings.get('General','MusicService',fallback=''),
                settings.get('General','MusicApp',fallback=''))
    except (OSError,configparser.Error):return '', ''

def control(bus,action,interface,preferred=('', ''),uri=''):
    if action=='PausePlaying':
        paused=[]
        for name in bus.list_names():
            if not str(name).startswith('org.mpris.MediaPlayer2.'):continue
            if not is_local_player(bus, name):continue
            try:
                obj=bus.get_object(name,'/org/mpris/MediaPlayer2')
                props=interface(obj,'org.freedesktop.DBus.Properties').GetAll('org.mpris.MediaPlayer2.Player',timeout=1)
                if str(props.get('PlaybackStatus'))!='Playing':continue
                interface(obj,'org.mpris.MediaPlayer2.Player').Pause(timeout=1)
                paused.append(str(name))
            except Exception:continue
        return 'Pause delivered to '+', '.join(paused) if paused else 'no eligible player'
    candidates=[]
    resume=action=='ResumePreferred'
    selected,desktop=preferred
    for name in bus.list_names():
        if not name.startswith('org.mpris.MediaPlayer2.'):continue
        try:
            if not is_local_player(bus, name):continue
            obj=bus.get_object(name,'/org/mpris/MediaPlayer2')
            props=interface(obj,'org.freedesktop.DBus.Properties').GetAll('org.mpris.MediaPlayer2.Player',timeout=2)
            if not props.get('CanControl',True):continue
            status=str(props.get('PlaybackStatus','Stopped'))
            if action=='PausePlaying' and status!='Playing':continue
            method='Pause' if action=='PausePlaying' else 'Play' if resume or action=='PlayExclusive' else action
            cap={'Next':'CanGoNext','Previous':'CanGoPrevious','Pause':'CanPause','Play':'CanPlay'}.get(method)
            stock=str(name).startswith('org.mpris.MediaPlayer2.jolla-mediaplayer')
            if cap and not props.get(cap,True) and not (method=='Play' and stock) and not (action=='PlayExclusive' and uri):continue
            match=str(name)==selected if selected else False
            if not match and desktop:
                try:
                    root=interface(obj,'org.freedesktop.DBus.Properties').GetAll('org.mpris.MediaPlayer2',timeout=2)
                    entry=str(root.get('DesktopEntry',''))
                    if entry.endswith('.desktop'):entry=entry[:-8]
                    match=entry==desktop
                except Exception:pass
            if (selected or desktop) and not match:continue
            candidates.append((0 if match else 1,0 if status=='Playing' else 1 if status=='Paused' else 2,str(name),obj,method,status,bool(props.get('CanPlay',True))))
        except Exception:continue
    if not candidates:return 'no eligible player'
    _,_,name,obj,method,status,can_play=sorted(candidates,key=lambda c:c[:3])[0]
    def perform():
        if method=='Play' and name.startswith('org.mpris.MediaPlayer2.jolla-mediaplayer') and (uri or not can_play):
            system_play(bus,interface,uri)
        elif action=='PlayExclusive' and uri:
            interface(obj,'org.mpris.MediaPlayer2.Player').OpenUri(uri,timeout=2)
        else:getattr(interface(obj,'org.mpris.MediaPlayer2.Player'),method)(timeout=2)
    if method=='Play' or (method=='PlayPause' and status!='Playing'):
        exclusive_play(bus,interface,name,perform)
    else:perform()
    return method+' delivered to '+name

def resume_marker_path():
    return Path.home() / '.config/sailplay/resume-playback'


def set_resume_marker(enabled):
    marker = resume_marker_path()
    try:
        if enabled:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text('1\n', encoding='utf-8')
        elif marker.exists():
            marker.unlink()
    except OSError:
        pass


def any_local_playing(bus, interface):
    for name in bus.list_names():
        if not str(name).startswith('org.mpris.MediaPlayer2.'):
            continue
        if not is_local_player(bus, name):
            continue
        try:
            obj = bus.get_object(name, '/org/mpris/MediaPlayer2')
            props = interface(obj, 'org.freedesktop.DBus.Properties').GetAll('org.mpris.MediaPlayer2.Player', timeout=1)
            if str(props.get('PlaybackStatus')) == 'Playing':
                return True
        except Exception:
            continue
    return False


def now_playing_snapshot(bus, interface):
    best = None
    for name in bus.list_names():
        if not str(name).startswith('org.mpris.MediaPlayer2.'):
            continue
        if not is_local_player(bus, name):
            continue
        try:
            obj = bus.get_object(name, '/org/mpris/MediaPlayer2')
            props_iface = interface(obj, 'org.freedesktop.DBus.Properties')
            props = props_iface.GetAll('org.mpris.MediaPlayer2.Player', timeout=1)
            status = str(props.get('PlaybackStatus', 'Stopped'))
            rank = 0 if status == 'Playing' else 1 if status == 'Paused' else 2
            meta = props.get('Metadata') or {}
            title = str(meta.get('xesam:title', ''))
            artists = meta.get('xesam:artist', [])
            if isinstance(artists, (list, tuple)):
                artist = ', '.join(str(a) for a in artists if a)
            else:
                artist = str(artists or '')
            album = str(meta.get('xesam:album', ''))
            length_us = int(meta.get('mpris:length', 0) or 0)
            pos_us = int(props.get('Position', 0) or 0)
            try:
                app = str(props_iface.Get('org.mpris.MediaPlayer2', 'Identity', timeout=1))
            except Exception:
                app = str(name).rsplit('.', 1)[-1]
            entry = (rank, str(name), {
                'status': status,
                'title': title,
                'artist': artist,
                'album': album,
                'durationMs': max(0, length_us // 1000),
                'positionMs': max(0, pos_us // 1000),
                'app': app,
            })
            if best is None or entry[:2] < best[:2]:
                best = entry
        except Exception:
            continue
    return best[2] if best is not None else {'status': 'Stopped', 'title': '', 'artist': '', 'album': '', 'durationMs': 0, 'positionMs': 0, 'app': ''}


def main():
    action=sys.argv[1] if len(sys.argv)>1 else ''
    if action=='--session-stop':
        marker='/run/sailplay-media-active'
        try:os.unlink(marker)
        except FileNotFoundError:return
        subprocess.run(['su','defaultuser','-s','/bin/sh','-c',
            'exec env DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket python3 /opt/sailplay/scripts/media-control.py PausePlaying'],timeout=4)
        return
    if action == 'NowPlaying':
        import dbus
        print(json.dumps(now_playing_snapshot(dbus.SessionBus(), dbus.Interface), ensure_ascii=False), flush=True)
        return
    if action not in ('Play','Pause','PlayPause','Next','Previous','PausePlaying','ResumePreferred','PlayExclusive'):raise ValueError('invalid media action')
    import dbus
    bus = dbus.SessionBus()
    if action == 'ResumePreferred':
        if any_local_playing(bus, dbus.Interface):
            set_resume_marker(False)
            print('already playing', flush=True)
            return
        if not resume_marker_path().exists():
            print('resume skipped', flush=True)
            return
        set_resume_marker(False)
    preferred=remembered_player()
    uri=''
    if action=='PlayExclusive':
        service=sys.argv[2]
        if not service.startswith('org.mpris.MediaPlayer2.'):raise ValueError('invalid player')
        preferred=(service,'')
        uri=sys.argv[3] if len(sys.argv)>3 else ''
        if uri:
            from urllib.parse import urlparse,unquote
            parsed=urlparse(uri)
            if parsed.scheme!='file' or parsed.netloc not in ('','localhost') or not Path(unquote(parsed.path)).is_file():
                raise ValueError('invalid media file')
    result = control(bus,action,dbus.Interface,preferred,uri)
    if action == 'PausePlaying':
        set_resume_marker('Pause delivered to ' in result)
    print(result,flush=True)
if __name__=='__main__':main()
