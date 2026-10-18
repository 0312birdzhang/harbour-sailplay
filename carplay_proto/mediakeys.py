"""Consumer-page HID media keys and session-owned player control."""
import os
import queue
import subprocess
import threading

ACTIONS={0xb0:'Play',0xb1:'Pause',0xb5:'Next',0xb6:'Previous',0xb7:'Pause',0xcd:'PlayPause'}
MARKER='/run/sailplay-media-active'

def consumer_layout(descriptor):
    page=size=count=report=minimum=0;usages=[];low=high=None;offsets={};layouts={};stack=[];i=0
    while i<len(descriptor):
        prefix=descriptor[i];i+=1
        if prefix==254:
            if i+2>len(descriptor):raise ValueError('truncated HID long item')
            n=descriptor[i];i+=2+n;continue
        n=(0,1,2,4)[prefix&3]
        if i+n>len(descriptor):raise ValueError('truncated HID item')
        value=int.from_bytes(descriptor[i:i+n],'little');i+=n
        kind=(prefix>>2)&3;tag=prefix>>4
        if kind==1:
            if tag==0:page=value
            elif tag==1:minimum=value
            elif tag==7:size=value
            elif tag==8:report=value
            elif tag==9:count=value
            elif tag==10:stack.append((page,size,count,report,minimum))
            elif tag==11:page,size,count,report,minimum=stack.pop()
        elif kind==2:
            if tag==0:usages.append((page,value))
            elif tag==1:low=value
            elif tag==2:high=value
        elif kind==0:
            if tag==8:
                if size>32 or count>256:raise ValueError('oversized HID media field')
                offset=offsets.get(report,0)
                if low is not None and high is not None:usages.extend((page,u) for u in range(low,min(high,low+255)+1))
                if not value&1 and page==12 and any(u in ACTIONS for pg,u in usages if pg==12):
                    layouts.setdefault(report,[]).append((offset,size,count,bool(value&2),minimum,tuple(usages)))
                offsets[report]=offset+size*count
            usages=[];low=high=None
    return layouts

def pressed_usages(layouts,data):
    report=data[0] if 0 not in layouts and data else 0
    if report not in layouts:raise ValueError('unknown media report')
    body=data[1:] if report else data;bits=int.from_bytes(body,'little');pressed=set()
    for offset,size,count,variable,minimum,usages in layouts[report]:
        if offset+size*count>len(body)*8:raise ValueError('short media report')
        for index in range(count):
            value=(bits>>(offset+size*index))&((1<<size)-1)
            usage=usages[min(index,len(usages)-1)] if variable else usages[value-minimum] if 0<=value-minimum<len(usages) else None
            if usage and usage[0]==12 and usage[1] in ACTIONS and (not variable or value):pressed.add(usage[1])
    return pressed

class MediaKeys:
    def __init__(self,devices):
        self.layouts={};self.pressed={};self.active=False
        for device in devices:
            try:layout=consumer_layout(bytes(device.get('hidDescriptor',b'')))
            except (ValueError,IndexError):continue
            if layout:self.layouts[str(device['uuid'])]=layout
        self.pending=queue.Queue(16);self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
        print('Media HID channels={}'.format(sorted(self.layouts)),flush=True)
    def call(self,action):
        try:
            result=subprocess.run(['su','defaultuser','-s','/bin/sh','-c',
                'exec env XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket python3 /opt/sailplay/scripts/media-control.py '+action],
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=4,universal_newlines=True)
            print('Media control {} exit={} {}'.format(action,result.returncode,result.stdout.strip()[:500]),flush=True)
        except Exception as error:print('Media control failed {} {}'.format(action,type(error).__name__),flush=True)
    def command(self,value):
        key=str(value.get('uuid'))
        if value.get('type')!='hidSendReport' or key not in self.layouts:return False
        data=bytes(value.get('hidReport',b''));now=pressed_usages(self.layouts[key],data)
        for usage in sorted(now-self.pressed.get(key,set())):
            action=ACTIONS[usage]
            print('Media HID uuid={} report={} usage=0x{:x} action={}'.format(key,data.hex(),usage,action),flush=True)
            try:self.pending.put_nowait(action)
            except queue.Full:print('Media control queue full',flush=True)
        self.pressed[key]=now
        return True
    def run(self):
        while not self.stop.is_set():
            try:action=self.pending.get(timeout=.1)
            except queue.Empty:continue
            if not self.stop.is_set():self.call(action)
    def started(self):
        self.active=True
        fd=os.open(MARKER,os.O_CREAT|os.O_WRONLY|os.O_TRUNC|os.O_NOFOLLOW,0o600);os.close(fd)
    def close(self):
        self.stop.set();self.thread.join(4.5)
        if self.active:
            try:os.unlink(MARKER)
            except FileNotFoundError:pass
            self.call('PausePlaying')
