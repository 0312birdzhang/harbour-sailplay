#!/usr/bin/env python3
"""Operate the existing phone MPRIS player, without launching an app."""
import os
import sys
import subprocess

def control(bus,action,interface):
    candidates=[]
    for name in bus.list_names():
        if not name.startswith('org.mpris.MediaPlayer2.'):continue
        try:
            obj=bus.get_object(name,'/org/mpris/MediaPlayer2')
            props=interface(obj,'org.freedesktop.DBus.Properties').GetAll('org.mpris.MediaPlayer2.Player',timeout=2)
            if not props.get('CanControl',True):continue
            status=str(props.get('PlaybackStatus','Stopped'))
            if action=='PausePlaying' and status!='Playing':continue
            method='Pause' if action=='PausePlaying' else action
            cap={'Next':'CanGoNext','Previous':'CanGoPrevious','Pause':'CanPause','Play':'CanPlay'}.get(method)
            if cap and not props.get(cap,True):continue
            candidates.append((0 if status=='Playing' else 1 if status=='Paused' else 2,str(name),obj,method))
        except Exception:continue
    if not candidates:return 'no eligible player'
    _,name,obj,method=sorted(candidates,key=lambda c:(c[0],c[1]))[0]
    getattr(interface(obj,'org.mpris.MediaPlayer2.Player'),method)(timeout=2)
    return method+' delivered to '+name

def main():
    action=sys.argv[1] if len(sys.argv)>1 else ''
    if action=='--session-stop':
        marker='/run/sailplay-media-active'
        try:os.unlink(marker)
        except FileNotFoundError:return
        subprocess.run(['su','defaultuser','-s','/bin/sh','-c',
            'exec env DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket python3 /opt/sailplay/scripts/media-control.py PausePlaying'],timeout=4)
        return
    if action not in ('Play','Pause','PlayPause','Next','Previous','PausePlaying'):raise ValueError('invalid media action')
    import dbus
    print(control(dbus.SessionBus(),action,dbus.Interface),flush=True)
if __name__=='__main__':main()
