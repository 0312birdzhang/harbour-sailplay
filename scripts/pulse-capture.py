#!/usr/bin/env python3
"""PulseAudio playback-monitor capture. Never falls back to a microphone."""
import ctypes as C
import ctypes.util
import os
import re
import signal
import subprocess
import sys
import time
import threading
import json
import audioop


def pactl(*args):
    return subprocess.check_output(['pactl']+list(args),stderr=subprocess.DEVNULL,
                                   env=dict(os.environ,LC_ALL='C'),timeout=3).decode()


def playback_volumes(output):
    result={}
    for block in re.split(r'(?m)^Sink Input #',output)[1:]:
        index=block.splitlines()[0].strip()
        line=next((line for line in block.splitlines() if line.strip().startswith('Volume:')), '')
        values=re.findall(r':\s*(\d+)\s*/',line)
        if values: result[index]=values
    return result


ROUTE_STATE=os.path.expanduser('~/.config/sailplay/audio-route-recovery.json')


def stream_diagnostics(output, heading='Sink Input'):
    """Keep routing evidence without recording media titles or filenames."""
    result=[]
    for block in re.split(r'(?m)^'+re.escape(heading)+r' #',output)[1:]:
        item={'id':block.splitlines()[0].strip()}
        for field in ('Sink','Source','Corked','Mute','Volume'):
            match=re.search(r'(?m)^\s*'+field+r':\s*(.+)$',block)
            if match:item[field.lower()]=match.group(1).strip()
        for field in ('application.process.binary','media.role','policy.group'):
            match=re.search(r'(?m)^\s*'+re.escape(field)+r'\s*=\s*"([^"]*)"',block)
            if match:item[field]=match.group(1)
        result.append(item)
    return result


def capture_gain(output):
    """Compensate media attenuation only in outgoing PCM, never in PA volumes."""
    media=[];other=[]
    for block in re.split(r'(?m)^Sink Input #',output)[1:]:
        if re.search(r'(?m)^\s*(Mute|Corked): yes\s*$',block):continue
        levels=list(playback_volumes('Sink Input #'+block).values())
        if not levels:continue
        volume=max(int(v) for v in levels[0])
        if volume<=0:continue
        target=media if re.search(r'(media\.role|policy\.group|xpolicy\.group)\s*=\s*"(?:music|media)"',block) else other
        target.append(volume)
    values=media or other
    if not values:return 1.0
    # PulseAudio volume is cubic; limit gain and saturate PCM rather than wrap.
    return min(64.0,(65536.0/max(values))**3)


def hardware_volumes(output):
    result={}
    for block in re.split(r'(?m)^Sink #',output)[1:]:
        name=re.search(r'(?m)^\s*Name:\s*(\S+)',block)
        values=playback_volumes('Sink Input #'+block)
        if name and values:result[name.group(1)]=next(iter(values.values()))
    return result


def restore_outputs():
    try:
        with open(ROUTE_STATE) as source:state=json.load(source)
    except FileNotFoundError:return
    for sink in state['mutes']:pactl('set-sink-mute',sink,'1')
    if state.get('default') and pactl('get-default-sink').strip()==state.get('cast'):
        pactl('set-default-sink',state['default'])
    # Remove only the private sink belonging to this recovery record. Moving
    # its remaining streams can alter flat hardware volumes, so do it muted
    # and restore hardware levels afterwards, before making output audible.
    cast=state.get('cast','')
    if cast.startswith('sailplay_cast_'):
        for line in pactl('list','short','modules').splitlines():
            fields=line.split(None,2)
            if (len(fields)==3 and fields[1]=='module-null-sink'
                    and re.search(r'(?:^|\s)sink_name='+re.escape(cast)+r'(?:\s|$)',fields[2])):
                pactl('unload-module',fields[0])
    # Restore levels while hardware is still muted. Legacy recovery files did
    # not save levels, so use a conservative level rather than expose 100%.
    for sink in state['mutes']:
        values=state.get('volumes',{}).get(sink)
        pactl('set-sink-volume',sink,*(values or ['25%']))
    for sink,muted in state['mutes'].items():
        pactl('set-sink-mute',sink,str(int(muted)))
    os.unlink(ROUTE_STATE)


def main():
    restore_outputs()
    stop=[False]
    signal.signal(signal.SIGTERM,lambda *_:stop.__setitem__(0,True))
    signal.signal(signal.SIGINT,lambda *_:stop.__setitem__(0,True))
    name='sailplay_cast_'+str(os.getpid())
    module=None; context=stream=loop=None; moved={}; callbacks=[]
    pcm_gain=[1.0]
    last_diagnostic=[0.0]
    router=None; route_stop=threading.Event();route_wake=threading.Event()
    sink_mutes={};default_sink=None
    lib=C.CDLL(ctypes.util.find_library('pulse'))
    signatures={
        'pa_mainloop_new':([],C.c_void_p), 'pa_mainloop_get_api':([C.c_void_p],C.c_void_p),
        'pa_mainloop_iterate':([C.c_void_p,C.c_int,C.c_void_p],C.c_int), 'pa_mainloop_free':([C.c_void_p],None),
        'pa_context_new':([C.c_void_p,C.c_char_p],C.c_void_p),
        'pa_context_connect':([C.c_void_p,C.c_char_p,C.c_int,C.c_void_p],C.c_int),
        'pa_context_get_state':([C.c_void_p],C.c_int), 'pa_context_disconnect':([C.c_void_p],None),
        'pa_context_unref':([C.c_void_p],None),
        'pa_context_set_subscribe_callback':([C.c_void_p,C.c_void_p,C.c_void_p],None),
        'pa_context_subscribe':([C.c_void_p,C.c_int,C.c_void_p,C.c_void_p],C.c_void_p),
        'pa_operation_unref':([C.c_void_p],None),
        'pa_stream_new':([C.c_void_p,C.c_char_p,C.c_void_p,C.c_void_p],C.c_void_p),
        'pa_stream_connect_record':([C.c_void_p,C.c_char_p,C.c_void_p,C.c_int],C.c_int),
        'pa_stream_get_state':([C.c_void_p],C.c_int), 'pa_stream_get_device_name':([C.c_void_p],C.c_char_p),
        'pa_stream_set_read_callback':([C.c_void_p,C.c_void_p,C.c_void_p],None),
        'pa_stream_peek':([C.c_void_p,C.POINTER(C.c_void_p),C.POINTER(C.c_size_t)],C.c_int),
        'pa_stream_drop':([C.c_void_p],C.c_int), 'pa_stream_disconnect':([C.c_void_p],C.c_int),
        'pa_stream_unref':([C.c_void_p],None)}
    for key,(args,result) in signatures.items():
        fn=getattr(lib,key);fn.argtypes=args;fn.restype=result
    class SampleSpec(C.Structure):
        _fields_=[('format',C.c_int),('rate',C.c_uint32),('channels',C.c_uint8)]
    def wait_state(object,getter,wanted):
        deadline=time.monotonic()+8
        while not stop[0]:
            state=getter(object)
            if state==wanted:return
            if state in (5,6) or time.monotonic()>deadline:raise RuntimeError('PulseAudio setup failed')
            lib.pa_mainloop_iterate(loop,0,None);time.sleep(.01)
        raise RuntimeError('capture stopped')
    def route():
        inputs=pactl('list','sink-inputs')
        pcm_gain[0]=capture_gain(inputs)
        now=time.monotonic()
        if now-last_diagnostic[0]>=10:
            snapshot={'cast':name,'gain':pcm_gain[0],
                      'inputs':stream_diagnostics(inputs),
                      'captures':stream_diagnostics(pactl('list','source-outputs'),'Source Output'),
                      'cast_mute':pactl('get-sink-mute',name).strip(),
                      'cast_volume':pactl('get-sink-volume',name).strip(),
                      'monitor_mute':pactl('get-source-mute',name+'.monitor').strip(),
                      'monitor_volume':pactl('get-source-volume',name+'.monitor').strip()}
            print('Audio route state '+json.dumps(snapshot,sort_keys=True),file=sys.stderr,flush=True)
            last_diagnostic[0]=now
        for line in pactl('list','short','sink-inputs').splitlines():
            fields=line.split()
            if len(fields)<2:continue
            index,sink=fields[:2]
            if sink!=sink_index:
                moved.setdefault(index,sink)
                try:pactl('move-sink-input',index,name)
                except subprocess.SubprocessError:continue
    def routing_loop():
        while not route_stop.is_set() and not stop[0]:
            try:route()
            except (subprocess.SubprocessError,OSError) as error:
                print('Audio routing maintenance failed: '+type(error).__name__,file=sys.stderr,flush=True)
            route_wake.wait(1);route_wake.clear()
    try:
        module=pactl('load-module','module-null-sink','sink_name='+name,'rate=48000','channels=2').strip()
        sink_index=next(l.split()[0] for l in pactl('list','short','sinks').splitlines() if l.split()[1]==name)
        default_sink=pactl('get-default-sink').strip()
        # Policy modules may initially select a hardware sink before the
        # stream-created notification reaches us. Keep that output silent.
        for line in pactl('list','short','sinks').splitlines():
            fields=line.split()
            if len(fields)>2 and fields[2]=='module-droid-card.c':
                sink=fields[1]
                sink_mutes[sink]=pactl('get-sink-mute',sink).strip().endswith('yes')
        os.makedirs(os.path.dirname(ROUTE_STATE),exist_ok=True)
        all_volumes=hardware_volumes(pactl('list','sinks'))
        recovery={'default':default_sink,'cast':name,'mutes':sink_mutes,
                  'volumes':{sink:all_volumes[sink] for sink in sink_mutes if sink in all_volumes}}
        fd=os.open(ROUTE_STATE+'.tmp',os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as saved:json.dump(recovery,saved)
        os.replace(ROUTE_STATE+'.tmp',ROUTE_STATE)
        pactl('set-default-sink',name)
        for sink in sink_mutes:pactl('set-sink-mute',sink,'1')
        print('CarPlay default output selected; phone hardware outputs protected',file=sys.stderr,flush=True)
        loop=lib.pa_mainloop_new();context=lib.pa_context_new(lib.pa_mainloop_get_api(loop),b'Sailplay monitor')
        if lib.pa_context_connect(context,None,0,None)<0:raise RuntimeError('PulseAudio connect failed')
        wait_state(context,lib.pa_context_get_state,4)
        @C.CFUNCTYPE(None,C.c_void_p,C.c_int,C.c_uint32,C.c_void_p)
        def changed(c,event,index,u):
            if event & 15 == 2:route_wake.set()
        callbacks.append(changed)
        lib.pa_context_set_subscribe_callback(context,changed,None)
        operation=lib.pa_context_subscribe(context,4,None,None)
        if not operation:raise RuntimeError('playback subscription failed')
        lib.pa_operation_unref(operation)
        spec=SampleSpec(3,48000,2)
        stream=lib.pa_stream_new(context,b'Sailplay playback capture',C.byref(spec),None)
        if not stream:raise RuntimeError('PulseAudio stream failed')
        @C.CFUNCTYPE(None,C.c_void_p,C.c_size_t,C.c_void_p)
        def read(s,n,u):
            peeked=False
            try:
                source=lib.pa_stream_get_device_name(s)
                if source!=(name+'.monitor').encode():raise RuntimeError('recording source mismatch: actual=%r expected=%r' % (source, (name+'.monitor').encode()))
                pointer=C.c_void_p();length=C.c_size_t()
                if lib.pa_stream_peek(s,C.byref(pointer),C.byref(length))<0:raise RuntimeError('monitor read failed')
                peeked=bool(length.value)
                if length.value and not stop[0]:
                    data=C.string_at(pointer,length.value) if pointer.value else bytes(length.value)
                    if pcm_gain[0]!=1.0:data=audioop.mul(data,2,pcm_gain[0])
                    view=memoryview(data)
                    while view:
                        written=os.write(1,view);view=view[written:]
            except Exception as error:
                print('Audio capture stopped: '+type(error).__name__+' '+str(error),file=sys.stderr,flush=True);stop[0]=True
            finally:
                if peeked:lib.pa_stream_drop(s)
        callbacks.append(read);lib.pa_stream_set_read_callback(stream,read,None)
        # DONT_MOVE protects against policy modules redirecting this to a microphone.
        if lib.pa_stream_connect_record(stream,(name+'.monitor').encode(),None,0x200)<0:raise RuntimeError('monitor connect failed')
        wait_state(stream,lib.pa_stream_get_state,2)
        print('Audio capturing '+name+'.monitor 48000Hz stereo S16LE',file=sys.stderr,flush=True)
        router=threading.Thread(target=routing_loop,daemon=True)
        router.start()
        while not stop[0]:
            if lib.pa_context_get_state(context)!=4 or lib.pa_stream_get_state(stream)!=2:raise RuntimeError('PulseAudio disconnected')
            lib.pa_mainloop_iterate(loop,0,None)
            time.sleep(.01)
    finally:
        route_stop.set()
        route_wake.set()
        if router:router.join()
        if stream:lib.pa_stream_disconnect(stream);lib.pa_stream_unref(stream)
        if context:lib.pa_context_disconnect(context);lib.pa_context_unref(context)
        if loop:lib.pa_mainloop_free(loop)
        for index,sink in moved.items():
            try:pactl('move-sink-input',index,sink)
            except subprocess.SubprocessError:pass
        if default_sink:
            try:
                if pactl('get-default-sink').strip()==name:pactl('set-default-sink',default_sink)
            except subprocess.SubprocessError:pass
        try:restore_outputs()
        except (subprocess.SubprocessError,OSError) as error:
            print('Audio output restoration pending: '+type(error).__name__,file=sys.stderr,flush=True)
        if module:
            try:pactl('unload-module',module)
            except subprocess.SubprocessError:pass
        print('Audio monitor removed; playback restored',file=sys.stderr,flush=True)

if __name__=='__main__':
    try:
        if '--restore-routing' in sys.argv:restore_outputs()
        else:main()
    except Exception as error:
        print('Audio capture failed: '+type(error).__name__+' '+str(error),file=sys.stderr,flush=True)
        sys.exit(1)
