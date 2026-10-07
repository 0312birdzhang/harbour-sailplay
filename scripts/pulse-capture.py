#!/usr/bin/env python3
"""PulseAudio playback-monitor capture. Never falls back to a microphone."""
import ctypes as C
import ctypes.util
import os
import signal
import subprocess
import sys
import time


def pactl(*args):
    return subprocess.check_output(['pactl']+list(args),stderr=subprocess.DEVNULL).decode()


def main():
    stop=[False]
    signal.signal(signal.SIGTERM,lambda *_:stop.__setitem__(0,True))
    signal.signal(signal.SIGINT,lambda *_:stop.__setitem__(0,True))
    name='sailplay_cast_'+str(os.getpid())
    module=None; context=stream=loop=None; moved={}; callbacks=[]
    lib=C.CDLL(ctypes.util.find_library('pulse'))
    signatures={
        'pa_mainloop_new':([],C.c_void_p), 'pa_mainloop_get_api':([C.c_void_p],C.c_void_p),
        'pa_mainloop_iterate':([C.c_void_p,C.c_int,C.c_void_p],C.c_int), 'pa_mainloop_free':([C.c_void_p],None),
        'pa_context_new':([C.c_void_p,C.c_char_p],C.c_void_p),
        'pa_context_connect':([C.c_void_p,C.c_char_p,C.c_int,C.c_void_p],C.c_int),
        'pa_context_get_state':([C.c_void_p],C.c_int), 'pa_context_disconnect':([C.c_void_p],None),
        'pa_context_unref':([C.c_void_p],None),
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
        for line in pactl('list','short','sink-inputs').splitlines():
            fields=line.split()
            if len(fields)<2:continue
            index,sink=fields[:2]
            if sink!=sink_index:
                moved.setdefault(index,sink)
                try:pactl('move-sink-input',index,name)
                except subprocess.CalledProcessError:pass
    try:
        module=pactl('load-module','module-null-sink','sink_name='+name,'rate=48000','channels=2').strip()
        sink_index=next(l.split()[0] for l in pactl('list','short','sinks').splitlines() if l.split()[1]==name)
        loop=lib.pa_mainloop_new();context=lib.pa_context_new(lib.pa_mainloop_get_api(loop),b'Sailplay monitor')
        if lib.pa_context_connect(context,None,0,None)<0:raise RuntimeError('PulseAudio connect failed')
        wait_state(context,lib.pa_context_get_state,4)
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
        last_route=0
        while not stop[0]:
            if lib.pa_context_get_state(context)!=4 or lib.pa_stream_get_state(stream)!=2:raise RuntimeError('PulseAudio disconnected')
            lib.pa_mainloop_iterate(loop,0,None)
            if time.monotonic()-last_route>1:route();last_route=time.monotonic()
            time.sleep(.01)
    finally:
        if stream:lib.pa_stream_disconnect(stream);lib.pa_stream_unref(stream)
        if context:lib.pa_context_disconnect(context);lib.pa_context_unref(context)
        if loop:lib.pa_mainloop_free(loop)
        for index,sink in moved.items():
            try:pactl('move-sink-input',index,sink)
            except subprocess.CalledProcessError:pass
        if module:
            try:pactl('unload-module',module)
            except subprocess.CalledProcessError:pass
        print('Audio monitor removed; playback restored',file=sys.stderr,flush=True)

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Audio capture failed: '+type(error).__name__+' '+str(error),file=sys.stderr,flush=True)
        sys.exit(1)
