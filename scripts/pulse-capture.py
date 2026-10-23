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


class BufferAttr(C.Structure):
    # Public libpulse ABI: five uint32_t fields, including maxlength.
    _fields_=[(name,C.c_uint32) for name in ('maxlength','tlength','prebuf','minreq','fragsize')]


def capture_buffer_attr():
    return BufferAttr(0xffffffff,0xffffffff,0xffffffff,0xffffffff,48000)


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


def muted_cast_streams(output,sink_index):
    """Only active playback already routed to our private sink is eligible."""
    return [item for item in stream_diagnostics(output)
            if item.get('sink')==str(sink_index) and item.get('mute')=='yes'
            and item.get('corked')=='no']


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


def main_volume_properties():
    import dbus
    bus=dbus.bus.BusConnection(os.environ.get('DBUS_SESSION_BUS_ADDRESS') or
                               'unix:path=/run/user/{}/dbus/user_bus_socket'.format(os.getuid()))
    lookup=dbus.Interface(bus.get_object('org.PulseAudio1','/org/pulseaudio/server_lookup1'),
                          'org.freedesktop.DBus.Properties')
    address=lookup.Get('org.PulseAudio.ServerLookup1','Address')
    connection=dbus.connection.Connection(str(address))
    return dbus.Interface(connection.get_object(object_path='/com/meego/mainvolume2'),
                          'org.freedesktop.DBus.Properties')


def save_main_volume():
    try:
        props=main_volume_properties().GetAll('com.Meego.MainVolume2')
        state={key:int(props[key]) for key in ('CurrentStep','StepCount')}
        state['CallState']=str(props['CallState'])
        print('Audio saved system volume step={}/{}'.format(state['CurrentStep'],state['StepCount']),file=sys.stderr,flush=True)
        return state
    except Exception as error:
        print('Audio system volume snapshot unavailable: '+str(error),file=sys.stderr,flush=True)
        return None


def restore_main_volume(state):
    old=state.get('mainVolume')
    if old is None:return
    import dbus
    props=main_volume_properties()
    current=props.GetAll('com.Meego.MainVolume2')
    if (int(current['StepCount'])!=old['StepCount'] or str(current['CallState'])!=old['CallState']):
        raise RuntimeError('system volume context changed; restoration retained for retry')
    props.Set('com.Meego.MainVolume2','CurrentStep',dbus.UInt32(old['CurrentStep']))
    actual=int(props.Get('com.Meego.MainVolume2','CurrentStep'))
    if actual!=old['CurrentStep']:raise RuntimeError('system volume restoration not confirmed')
    print('Audio restored system volume step={}/{}'.format(actual,old['StepCount']),file=sys.stderr,flush=True)


def save_recovery(state):
    fd=os.open(ROUTE_STATE+'.tmp',os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as saved:json.dump(state,saved)
    os.replace(ROUTE_STATE+'.tmp',ROUTE_STATE)


def private_playback(output,sink_index):
    volumes=playback_volumes(output)
    return [(item,volumes.get(item['id'],[])) for item in stream_diagnostics(output)
            if item.get('sink')==str(sink_index) and item.get('corked')=='no']


def private_playback_all(output):
    volumes=playback_volumes(output)
    return [(item,volumes.get(item['id'],[])) for item in stream_diagnostics(output)]


def restore_private_inputs(state):
    cast=state.get('cast','')
    if not cast.startswith('sailplay_cast_'):return
    index=next((l.split()[0] for l in pactl('list','short','sinks').splitlines() if len(l.split())>1 and l.split()[1]==cast),None)
    if index is None:return
    current={item['id']:item for item in stream_diagnostics(pactl('list','sink-inputs'))}
    for key,old in state.get('streams',{}).items():
        item=current.get(key,{})
        if not item or item.get('sink')!=index or item.get('application.process.binary')!=old.get('binary'):continue
        try:
            if old.get('volumes'):pactl('set-sink-input-volume',key,*old['volumes'])
            pactl('set-sink-input-mute',key,str(int(old.get('mute',False))))
        except subprocess.SubprocessError:pass


# Only Droid HAL sinks are muted during casting. Ports whose primary output
# is a plain ALSA sink (sink.primary_output via module-alsa-sink) are left
# alone: muting it makes the Sailfish audio policy attenuate the streams on
# the private sink (measured: a steady tone fell from full scale to ~2%).
HARDWARE_SINK_MODULES=('module-droid-card.c',)


def hardware_sinks(short_sinks):
    """Phone output sinks that are muted while casting (Droid HAL sinks)."""
    return [fields[1] for fields in (line.split() for line in short_sinks.splitlines())
            if len(fields)>2 and fields[2] in HARDWARE_SINK_MODULES]


def restore_outputs():
    try:
        with open(ROUTE_STATE) as source:state=json.load(source)
    except FileNotFoundError:return
    for sink in state['mutes']:pactl('set-sink-mute',sink,'1')
    restore_private_inputs(state)
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
    restore_main_volume(state)
    for sink,muted in state['mutes'].items():
        pactl('set-sink-mute',sink,str(int(muted)))
    os.unlink(ROUTE_STATE)


def load_private_sink(name):
    """Allow a brief PulseAudio restart without tearing down CarPlay."""
    for attempt in range(5):
        try:
            return pactl('load-module','module-null-sink','sink_name='+name,'rate=48000','channels=2').strip()
        except subprocess.CalledProcessError:
            if attempt==4:raise
            print('Audio server not ready; retrying private sink {}/4'.format(attempt+1),file=sys.stderr,flush=True)
            time.sleep(.5)


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
    stream_mutes={}
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
        'pa_stream_get_buffer_attr':([C.c_void_p],C.POINTER(BufferAttr)),
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
        before={item['id']:(item,volumes) for item,volumes in private_playback_all(pactl('list','sink-inputs'))}
        for line in pactl('list','short','sink-inputs').splitlines():
            fields=line.split()
            if len(fields)<2:continue
            index,sink=fields[:2]
            if sink!=sink_index:
                moved.setdefault(index,sink)
                if index not in recovery['streams'] and index in before:
                    item,volumes=before[index]
                    recovery['streams'][index]={'binary':item.get('application.process.binary'),
                        'mute':item.get('mute')=='yes','volumes':volumes}
                    save_recovery(recovery)
                try:pactl('move-sink-input',index,name)
                except subprocess.SubprocessError:continue
        inputs=pactl('list','sink-inputs')
        for item,volumes in private_playback(inputs,sink_index):
            if item.get('mute')!='yes' and volumes and all(int(v)==65536 for v in volumes):continue
            key=item['id']
            if key not in recovery['streams']:
                recovery['streams'][key]={'binary':item.get('application.process.binary'),
                    'mute':item.get('mute')=='yes','volumes':volumes}
                save_recovery(recovery)
            if item.get('mute')=='yes':pactl('set-sink-input-mute',key,'0')
            if volumes and any(int(v)!=65536 for v in volumes):pactl('set-sink-input-volume',key,'100%')
            print('Audio private playback independent level id='+key,file=sys.stderr,flush=True)
        # Only private render/monitor levels are normalized; physical outputs
        # and the user's hardware volume are never raised by this path.
        for kind,device in (('sink',name),('source',name+'.monitor')):
            if pactl('get-'+kind+'-mute',device).strip().endswith('yes'):pactl('set-'+kind+'-mute',device,'0')
            volume=pactl('get-'+kind+'-volume',device)
            levels=re.findall(r':\s*(\d+)\s*/',volume)
            if any(int(v)!=65536 for v in levels):pactl('set-'+kind+'-volume',device,'100%')
        pcm_gain[0]=1.0
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
    def routing_loop():
        while not route_stop.is_set() and not stop[0]:
            try:route()
            except (subprocess.SubprocessError,OSError) as error:
                print('Audio routing maintenance failed: '+type(error).__name__,file=sys.stderr,flush=True)
            route_wake.wait(1);route_wake.clear()
    try:
        main_volume=save_main_volume()
        module=load_private_sink(name)
        sink_index=next(l.split()[0] for l in pactl('list','short','sinks').splitlines() if l.split()[1]==name)
        default_sink=pactl('get-default-sink').strip()
        # Policy modules may initially select a hardware sink before the
        # stream-created notification reaches us. Keep that output silent.
        for sink in hardware_sinks(pactl('list','short','sinks')):
            sink_mutes[sink]=pactl('get-sink-mute',sink).strip().endswith('yes')
        os.makedirs(os.path.dirname(ROUTE_STATE),exist_ok=True)
        all_volumes=hardware_volumes(pactl('list','sinks'))
        recovery={'default':default_sink,'cast':name,'mutes':sink_mutes,
                  'volumes':{sink:all_volumes[sink] for sink in sink_mutes if sink in all_volumes},'streams':{},'mainVolume':main_volume}
        save_recovery(recovery)
        # The default sink is deliberately left alone: making the private
        # sink the default lets the Sailfish audio policy attenuate every
        # stream on it (measured: a steady tone fell from full scale to ~2%),
        # so the car received near silence. Streams are moved by route()
        # as soon as they appear.
        for sink in sink_mutes:pactl('set-sink-mute',sink,'1')
        print('CarPlay output routing active; phone hardware outputs protected: '+(','.join(sink_mutes) or 'none'),
              file=sys.stderr,flush=True)
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
        attrs=capture_buffer_attr()
        if lib.pa_stream_connect_record(stream,(name+'.monitor').encode(),C.byref(attrs),0x200|0x2000)<0:raise RuntimeError('monitor connect failed')
        wait_state(stream,lib.pa_stream_get_state,2)
        actual=lib.pa_stream_get_buffer_attr(stream)
        if actual:print('Audio record buffer fragsize={} maxlength={} requestedFragmentMs=250'.format(actual.contents.fragsize,actual.contents.maxlength),file=sys.stderr,flush=True)
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
        if default_sink:
            try:restore_private_inputs(recovery)
            except (subprocess.SubprocessError,OSError):pass
        for index in stream_mutes:
            try:pactl('set-sink-input-mute',index,'1')
            except subprocess.SubprocessError:pass
        for index,sink in moved.items():
            try:pactl('move-sink-input',index,sink)
            except subprocess.SubprocessError:pass
        if default_sink:
            try:
                if pactl('get-default-sink').strip()==name:pactl('set-default-sink',default_sink)
            except subprocess.SubprocessError:pass
        try:restore_outputs()
        except Exception as error:
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
