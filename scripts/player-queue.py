#!/usr/bin/python3
"""Read and select provider-owned queues without replacing them in the shell."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

def module(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value

def revision(items):
    return hashlib.sha256(json.dumps([row['key'] for row in items],ensure_ascii=False).encode()).hexdigest()

def sdk_request(provider,action,parameters,timeout=4):
    """Run one action in a short SDK car session of a "queue" provider."""
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from sailplay_sdk.client import SessionClient
    DBusGMainLoop(set_as_default=True)
    loop=GLib.MainLoop();outcome={}
    def finish(result,error):
        outcome.setdefault('value',(result,error));loop.quit()
        return False
    client=SessionClient(provider[0],'car',('queue',),provider[1],
        on_ready=lambda ready:ready and client.invoke(action,dbus.Dictionary(parameters,signature='sv')),
        on_request=lambda request,revision,result,name,message:finish(result,name),
        on_error=lambda name,message:finish({},name or 'failed'))
    GLib.timeout_add(int(timeout*1000),finish,{},'timeout')
    try:
        client.open();loop.run()
    finally:
        client.close()
    result,error=outcome['value']
    if error:raise ValueError('queue provider failed: '+error)
    return result

def sdk_queue(provider):
    value=sdk_request(provider,'queue.read',{}).get('queue')
    rows=None if not hasattr(value,'get') else value.get('items')
    if not isinstance(rows,(list,tuple)) or len(rows)>10000:raise ValueError('invalid provider queue')
    items=[]
    for index,row in enumerate(rows):
        if not hasattr(row,'get') or not isinstance(row.get('id'),str) or not row.get('id'):
            raise ValueError('invalid provider song')
        items.append({'key':str(row['id']),'title':str(row.get('title',''))[:1024],
                      'artist':str(row.get('subtitle',''))[:1024],'index':index})
    selected=int(value.get('index',-1))
    return items,selected if 0<=selected<len(items) else -1

def queue(bus,service,interface,provider=None):
    if provider:
        items,selected=sdk_queue(provider)
    elif service=='org.mpris.MediaPlayer2.harbour_mconnect':
        lyrics=module('queue_core','player-lyrics.py')
        owner=bus.get_name_owner('org.sailfishos.Mconnect.Core')
        api=interface(bus.get_object(owner,'/org/sailfishos/Mconnect/Core'),'org.sailfishos.Mconnect.Core')
        deadline=time.monotonic()+2.5
        rows=lyrics.core_request(api,'queue',deadline)
        state=lyrics.core_request(api,'snapshot',deadline)
        if not isinstance(rows,list) or len(rows)>10000:raise ValueError('invalid Mconnect queue')
        items=[]
        for index,row in enumerate(rows):
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not isinstance(row.get('platform'),str):
                raise ValueError('invalid Mconnect song')
            items.append({'key':row['platform']+':'+row['id'],'title':str(row.get('title','')),
                          'artist':str(row.get('artist','')),'index':index})
        current=state.get('song',{})
        key=str(current.get('platform',''))+':'+str(current.get('id',''))
        selected=next((i for i,row in enumerate(items) if row['key']==key),-1)
    elif service.startswith('org.mpris.MediaPlayer2.jolla-mediaplayer'):
        api=interface(bus.get_object('com.jolla.mediaplayer','/com/jolla/mediaplayer/sailplay'),'com.jolla.mediaplayer.sailplay')
        value=json.loads(str(api.snapshot(timeout=3)))
        if not value.get('ready'):return {'items':[],'index':-1,'revision':'','loading':True}
        rows=value.get('items')
        if not isinstance(rows,list) or len(rows)>10000:raise ValueError('invalid system queue')
        items=[]
        for index,row in enumerate(rows):
            if not isinstance(row,dict) or not isinstance(row.get('uri'),str):raise ValueError('invalid system song')
            items.append({'key':row['uri'],'title':str(row.get('title','')),'artist':str(row.get('artist','')),'index':index})
        selected=int(value.get('index',-1))
    else:raise ValueError('unsupported queue provider')
    return {'items':items,'index':selected,'revision':revision(items),'loading':False}

def play(bus,service,index,key,expected,interface,provider=None):
    before=queue(bus,service,interface,provider)
    if before['revision']!=expected or not 0<=index<len(before['items']) or before['items'][index]['key']!=key:
        raise ValueError('queue changed; refresh required')
    def perform():
        if provider:
            import dbus
            sdk_request(provider,'queue.play',{'index':dbus.UInt32(index),'id':dbus.String(key)})
        elif service=='org.mpris.MediaPlayer2.harbour_mconnect':
            api=interface(bus.get_object('org.sailfishos.Mconnect.Core','/org/sailfishos/Mconnect/Core'),'org.sailfishos.Mconnect.Core')
            api.Request('playIndex',json.dumps({'index':index}),timeout=3)
        else:
            api=interface(bus.get_object('com.jolla.mediaplayer','/com/jolla/mediaplayer/sailplay'),'com.jolla.mediaplayer.sailplay')
            if not api.playIndex(index,signature='i',timeout=3):raise ValueError('system queue unavailable')
    controls=module('queue_controls','media-control.py')
    controls.exclusive_play(bus,interface,service,perform)
    return {'ok':True}

if __name__=='__main__':
    import dbus
    action,service=sys.argv[1:3]
    if not service.startswith('org.mpris.MediaPlayer2.'):raise ValueError('invalid player')
    try:
        bus=dbus.SessionBus()
        # Sailplay appends the SDK service and path of a "queue" provider.
        provider=tuple(sys.argv[3:5] if action=='read' else sys.argv[6:8])
        if len(provider)!=2:provider=None
        result=(queue(bus,service,dbus.Interface,provider) if action=='read'
                else play(bus,service,int(sys.argv[3]),sys.argv[4],sys.argv[5],dbus.Interface,provider))
    except Exception:
        result={'ok':False,'items':[],'index':-1,'revision':'','error':True}
    print(json.dumps(result,ensure_ascii=False))
