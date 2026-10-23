"""Finite H.264 demo sender; no compositor, capture or audio changes."""
import re
import socket
import struct
import threading
import time
import plistlib
import os
import stat
import copy
from . import crypto
from .controlcipher import ControlCipher
from .rtspclient import EncryptedSocket, connect


def describe_params(value, limit=64):
    """Summarise a command plist for the log, shortening binary payloads."""
    if isinstance(value, dict):
        return {key: describe_params(item, limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [describe_params(item, limit) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return 'bytes[{}]:{}{}'.format(len(value), bytes(value[:limit]).hex(),
                                       '...' if len(value) > limit else '')
    return value


def demo_frames(data):
    nals = [n for n in re.split(b'\x00\x00\x00?\x01', data) if n]
    sps = next(n for n in nals if n[0] & 31 == 7)
    pps = next(n for n in nals if n[0] & 31 == 8)
    config = bytes([1, sps[1], sps[2], sps[3], 255, 225]) + struct.pack('>H',len(sps)) + sps
    config += b'\x01' + struct.pack('>H',len(pps)) + pps
    frames, current = [], []
    for nal in nals:
        if nal[0] & 31 not in (1,5):
            continue
        # first_mb_in_slice ue(v)==0 starts with a one bit. Retain other slices.
        if len(nal) < 2:
            raise ValueError('truncated video slice')
        if nal[1] & 128 and current:
            frames.append(current)
            current = []
        current.append(nal)
    if current:
        frames.append(current)
    if not frames or frames[0][0][0] & 31 != 5:
        raise ValueError('demo must begin with IDR')
    return config, frames


class ScreenEncoder:
    def __init__(self, shared, stream_id):
        self.key = crypto.hkdf_sha512(shared, ('DataStream-Salt'+str(stream_id)).encode(),
                                     b'DataStream-Output-Encryption-Key',32)
        self.counter = 0
        from .nativecrypto import NativeChaCha
        self.native = NativeChaCha(self.key)

    @staticmethod
    def _timestamp(timestamp_ns):
        seconds, fraction = divmod(timestamp_ns,1000000000)
        return (seconds << 32) | ((fraction << 32)//1000000000)

    def _header(self,size,payload_type,timestamp_ns,width,height,idr=False):
        # AirPlay screen packets: little-endian size, 2-byte type, 2-byte
        # option, then a fixed-point NTP timestamp. IDR slices are flagged in
        # the second type byte; receivers that ignore the flag still parse the
        # VCL NAL type, but strict head units need it.
        header = bytearray(128)
        struct.pack_into('<I',header,0,size)
        header[4] = payload_type
        header[5] = 0x10 if idr else 0
        struct.pack_into('<H',header,6,6)
        struct.pack_into('<Q',header,8,self._timestamp(timestamp_ns))
        if payload_type == 1:
            struct.pack_into('<ff',header,16,width,height)
        struct.pack_into('<ff',header,40,width,height)
        struct.pack_into('<ff',header,56,max(0,width-1),max(0,height-1))
        return header

    def config(self, avcc, width, height, timestamp_ns=None):
        if timestamp_ns is None:
            timestamp_ns = time.monotonic_ns()
        header = self._header(len(avcc),1,timestamp_ns,width,height)
        # Unencrypted H.264 SPS/PPS packet option used by iOS senders.
        header[6:8] = b'\x16\x01'
        return bytes(header)+avcc

    def frame(self, nals, timestamp_ns, width, height):
        body = b''.join(struct.pack('>I',len(n))+n for n in nals)
        idr = any(n and (n[0] & 31) == 5 for n in nals)
        header = self._header(len(body)+16,0,timestamp_ns,width,height,idr)
        encrypted = self.native.seal(crypto.nonce64(self.counter),body,bytes(header))
        self.counter += 1
        return bytes(header)+encrypted


class DemoEvents:
    def __init__(self,address,port,interface,shared,handler=None):
        self.handler=handler
        self.received = 0
        self.last_received = None
        transport = connect(address,port,interface)
        # The touch channel can be idle for minutes while video stays busy.
        transport.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        transport.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 15)
        transport.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
        transport.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        transport.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Events is an inbound request channel: phone acts as RTSP server.
        read = crypto.hkdf_sha512(shared,b'Events-Salt',b'Events-Write-Encryption-Key',32)
        write = crypto.hkdf_sha512(shared,b'Events-Salt',b'Events-Read-Encryption-Key',32)
        self.sock = EncryptedSocket(transport.sock,ControlCipher(read,write))
        self.sock.sock.settimeout(None)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        buf = b''
        try:
            while not self.stop.is_set():
                while b'\r\n\r\n' not in buf:
                    block = self.sock.recv(16384)
                    if not block:
                        print('Demo event channel closed by head unit (received={})'.format(self.received),flush=True)
                        return
                    buf += block
                    if len(buf)>65536:
                        raise ValueError('event header too large')
                head,buf = buf.split(b'\r\n\r\n',1)
                lines = head.decode('ascii').split('\r\n')
                headers = dict(line.lower().split(':',1) for line in lines[1:])
                size = int(headers.get('content-length','0'))
                if not 0<=size<=1048576:
                    raise ValueError('event body too large')
                while len(buf)<size:
                    block = self.sock.recv(16384)
                    if not block:
                        print('Demo event channel closed by head unit (received={})'.format(self.received),flush=True)
                        return
                    buf += block
                body,buf = buf[:size],buf[size:]
                self.received += 1
                self.last_received = time.monotonic()
                print('Demo event: {} bytes={}'.format(lines[0],size),flush=True)
                code=200
                reply=b''
                if body:
                    try:
                        value = plistlib.loads(body)
                        print('Demo event keys={}'.format(sorted(value)),flush=True)
                        print('Event command type={}'.format(value.get('type')),flush=True)
                        if value.get('type') not in ('hidSendReport','forceKeyFrame','iAPSendMessage'):
                            print('Event command detail={}'.format(describe_params(value)),flush=True)
                        if value.get('type')=='iAPSendMessage':
                            # iAP2 tunnelled over the AirPlay event channel;
                            # not handled yet, so record what the HU sends.
                            print('iAP tunnel params={}'.format(
                                describe_params(value.get('params'),2048)),flush=True)
                        if self.handler and lines[0].split()[1]=='/command':
                            result=self.handler(value)
                            if result is not None:
                                reply=plistlib.dumps(result,fmt=plistlib.FMT_BINARY)
                    except Exception as error:
                        print('Event handler failed: {}: {}'.format(type(error).__name__,error),flush=True)
                        code=400
                self.sock.sendall(('RTSP/1.0 {} {}\r\nCSeq: {}\r\nContent-Type: application/x-apple-binary-plist\r\nContent-Length: {}\r\n\r\n'.format(
                    code,'OK' if code==200 else 'Bad Request',headers.get('cseq','0').strip(),len(reply))).encode()+reply)
        except Exception as error:
            if not self.stop.is_set():
                print('Demo event channel: {}: {}'.format(type(error).__name__,error),flush=True)
        finally:
            self.stop.set()

    def close(self):
        self.stop.set()
        try:
            self.sock.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.thread.join(1)


class UiCommands:
    """Session-owned pipe accepting only the fixed OEM-screen action."""
    def __init__(self, path='/tmp/sailplay-ui-command'):
        self.path = path
        self.fd = self.writer = None
        self.buffer = b''
        self.resume = threading.Event()
        if os.path.lexists(path):
            old = os.lstat(path)
            if not stat.S_ISFIFO(old.st_mode) or old.st_uid != os.geteuid():
                raise RuntimeError('unsafe UI command path')
            os.unlink(path)
        os.mkfifo(path, 0o622)
        os.chmod(path, 0o622)
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        self.writer = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        self.identity = os.fstat(self.fd).st_ino

    def return_requested(self):
        try:
            self.buffer += os.read(self.fd, 4096)
        except BlockingIOError:
            pass
        lines = self.buffer.split(b'\n')
        self.buffer = lines.pop()[-128:]
        if b'show-carplay' in lines:
            self.resume.set()
        return b'return-car' in lines

    def close(self):
        for fd in (self.writer, self.fd):
            if fd is not None:
                os.close(fd)
        if os.path.lexists(self.path) and os.lstat(self.path).st_ino == self.identity:
            os.unlink(self.path)


class ScreenFeedback:
    """Keep control requests away from the video producer's critical path."""
    def __init__(self,client,commands=None,modes=None,resume=None,screen=None,resource_changed=None,audio=None,duck=None,mode_lock=None,mode_revision=None):
        self.client=client
        self.commands=commands
        self.modes=modes
        self.resume=resume
        self.screen=screen
        self.resource_changed=resource_changed
        self.audio=audio
        self.duck=duck if duck is not None else [1.0]
        self.mode_lock=mode_lock or threading.RLock()
        self.mode_revision=mode_revision if mode_revision is not None else [0]
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        next_feedback=time.monotonic()+2
        while not self.stop.wait(0.1):
            try:
                returning=self.commands and self.commands.return_requested()
                resuming=(self.resume is not None and self.resume.is_set()) or (self.commands and self.commands.resume.is_set())
                changed=self.resource_changed is not None and self.resource_changed.is_set()
                if returning or resuming or changed:
                    if changed:self.resource_changed.clear()
                    if resuming:
                        if self.resume is not None:
                            self.resume.clear()
                        if self.commands:
                            self.commands.resume.clear()
                    reason='CarPlay' if resuming else 'OEM' if returning else 'HU resource transfer'
                    print('Screen ownership command: '+reason,flush=True)
                    with self.mode_lock:
                        revision=self.mode_revision[0]
                        proposed=copy.deepcopy(self.modes)
                    if resuming:
                        # Native MODE switches deliver Play + requestUI after
                        # taking BOTH resources for FM. Reclaim both together.
                        for resource in proposed['resources']:
                            if resource['resourceID'] in (1,2):resource.update(entity=1,permanentEntity=1)
                    elif returning:
                        next(r for r in proposed['resources'] if r['resourceID']==1).update(entity=2,permanentEntity=2)
                    owner=next(r['entity'] for r in proposed['resources'] if r['resourceID']==1)
                    payload=plistlib.dumps({'type':'modesChanged','params':proposed},fmt=plistlib.FMT_BINARY)
                    status,_,body=self.client.request('POST','/command',payload,
                        {'Content-Type':'application/x-apple-binary-plist'})
                    command_status=plistlib.loads(body).get('status',0) if body else 0
                    accepted=status==200 and command_status==0
                    if accepted:
                        with self.mode_lock:
                            current=self.mode_revision[0]==revision
                            if current:
                                self.modes.update(proposed)
                                self.mode_revision[0]+=1
                                if self.audio:
                                    entity=next(r['entity'] for r in self.modes['resources'] if r['resourceID']==2)
                                    self.audio.gain=self.duck[0] if entity==1 else 0.0
                                    print('Audio resource reconciled entity={} senderGain={}'.format(entity,self.audio.gain),flush=True)
                        if current and self.screen:self.screen.ownership(owner)
                        elif not current and self.resource_changed is not None:self.resource_changed.set()
                    elif changed:
                        raise RuntimeError('HU resource notification rejected')
                    print('Screen ownership response owner={} status={} command_status={} accepted={}'.format(owner,status,command_status,accepted),flush=True)
                if time.monotonic()<next_feedback:
                    continue
                status,_,body=self.client.request('POST','/feedback',headers={'User-Agent':'AirPlay/566.25.21'})
                next_feedback=time.monotonic()+2
                print('Screen feedback status={} bytes={}'.format(status,len(body)),flush=True)
            except Exception as error:
                print('Screen feedback failed: {}: {}'.format(type(error).__name__,error),flush=True)
                self.stop.set()
                return

    def close(self):
        self.stop.set()
        self.thread.join(6)


def send_iap(client,data):
    """Send tunnelled iAP2 bytes to the head unit as an iAPSendMessage command."""
    try:
        status,_,body=client.request('POST','/command',plistlib.dumps(
            {'type':'iAPSendMessage','params':{'data':data}},fmt=plistlib.FMT_BINARY),
            {'Content-Type':'application/x-apple-binary-plist'})
        result=plistlib.loads(body).get('status',0) if body else 0
        print('iAP tunnel sent bytes={} HTTP={} status={} data={}'.format(
            len(data),status,result,describe_params(data,256)),flush=True)
    except Exception as error:
        print('iAP tunnel send failed: {}: {}'.format(type(error).__name__,error),flush=True)


def disable_bluetooth(client,address):
    """Ask the authenticated receiver to hand off BT; leave the adapter powered."""
    import re
    if not re.fullmatch(r'[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}',str(address)):
        raise ValueError('invalid local Bluetooth address')
    status,_,body=client.request('POST','/command',plistlib.dumps(
        {'type':'disableBluetooth','params':{'deviceID':address.upper()}},fmt=plistlib.FMT_BINARY),
        {'Content-Type':'application/x-apple-binary-plist'})
    result=plistlib.loads(body).get('status',0) if body else 0
    print('Bluetooth handoff localAddress={} HTTP={} result={}'.format(address,status,result),flush=True)
    if status!=200 or result!=0:raise RuntimeError('Bluetooth handoff rejected')


def run_demo(client,address,interface,shared,setup_info,info,path=None,seconds=15,live=False,on_activity=None,bluetooth_address=None,iap_link=None):
    display = info['displays'][0]
    pipeline = None
    width,height,fps=1920,720,30
    if live:
        from .displaysettings import load_settings, publish_display
        publish_display(display)
        width,height,fps=load_settings(display=display)
        print('Projection settings: {}x{} {}fps'.format(width,height,fps),flush=True)
    if not live:
        with open(path,'rb') as demo_file:
            config,frames = demo_frames(demo_file.read())
    if not live and (int(display['widthPixels']),int(display['heightPixels'])) != (1920,720):
        raise ValueError('demo requires 1920x720 display')
    stream_id = int.from_bytes(__import__('os').urandom(7),'big') or 1
    touch = audio = power = media = None
    resume = threading.Event()
    resource_changed=threading.Event()
    mode_lock=threading.RLock();mode_revision=[0];duck=[1.0]
    modes={'appStates':[{'appStateID':1,'entity':0,'speechMode':-1},
                        {'appStateID':2,'entity':0},{'appStateID':3,'entity':0}],
           'resources':[{'resourceID':r,'entity':1,'permanentEntity':1} for r in (1,2)]}
    keyframe_request=[0.0]
    iap_tunnel=None
    if iap_link:
        # Replies go out at once from the tunnel's own thread; RTSPClient
        # serialises them with the session's other control requests.
        from .iaptunnel import IAPTunnel
        iap_tunnel=IAPTunnel(iap_link,lambda data:send_iap(client,data))
    def event_command(value):
        if value.get('type')=='iAPSendMessage' and iap_tunnel:
            from .iaptunnel import tunnel_payload
            data=tunnel_payload(value)
            if data:
                iap_tunnel.feed(data)
            return {'status':0}
        if value.get('type')=='forceKeyFrame':
            now=time.monotonic()
            if pipeline is not None and now-keyframe_request[0]>=0.5:
                keyframe_request[0]=now
                try:
                    pipeline.request_keyframe()
                    print('HU requested keyframe; capture IDR requested',flush=True)
                except Exception as error:
                    print('Keyframe request failed: {}: {}'.format(type(error).__name__,error),flush=True)
            return {'status':0}
        handled=media.command(value) if media else False
        if touch and not handled:
            touch.command(value)
        if value.get('type')=='requestUI':
            resume.set()
            return {'status':0}
        if value.get('type')=='changeModes':
            print('HU mode transfer request resources={}'.format(
                value.get('params',{}).get('resources',[])),flush=True)
            with mode_lock:
                for request in value.get('params',{}).get('resources',[]):
                    resource=next((r for r in modes['resources'] if r['resourceID']==request.get('resourceID')),None)
                    if resource is not None:
                        transfer=request.get('transferType')
                        if transfer in (1,3): resource['entity']=2
                        elif transfer==2:resource['entity']=1
                        elif transfer==4:resource['entity']=resource['permanentEntity']
                        if transfer in (1,2):resource['permanentEntity']=resource['entity']

                if audio:
                    audio.gain=duck[0] if modes['resources'][1]['entity']==1 else 0.0
                    print('Audio ownership entity={} senderGain={}'.format(
                        modes['resources'][1]['entity'],audio.gain),flush=True)
                mode_revision[0]+=1
                if screen:screen.expect_owner(modes['resources'][0]['entity'])
                resource_changed.set()
            print('HU mode request applied: {}'.format(modes['resources']),flush=True)
            return {'status':0,'params':copy.deepcopy(modes)}
        if audio and value.get('type') in ('duckAudio','unduckAudio'):
            volume=max(-144,min(0,float(value.get('params',{}).get('volume',0))))
            with mode_lock:
                duck[0]=10**(volume/20) if value['type']=='duckAudio' else 1.0
                audio.gain=duck[0] if modes['resources'][1]['entity']==1 else 0.0
            print('Audio duck command={} volumeDb={} senderGain={}'.format(
                value['type'],volume,audio.gain),flush=True)
    if live:
        from .mediakeys import MediaKeys
        media=MediaKeys(info.get('hidDevices',[]))
        from .touch import TouchInput
        touch=TouchInput(info.get('hidDevices',[]),display['uuid'],width,height)
    events = None
    video = None
    feedback = None
    ended_audio = None
    commands = None
    screen = None
    try:
        if live:
            from .projectionpower import ProjectionPower
            power = ProjectionPower(lambda: {
                'events': events.received if events else 0,
                'event_age': round(time.monotonic() - events.last_received, 1)
                             if events and events.last_received is not None else None,
                'event_thread_alive': bool(events and events.thread.is_alive()),
            })
            power.start()
        events = DemoEvents(address,int(setup_info['eventPort']),interface,shared,
                            event_command)
        first_live_frame = None
        if live:
            commands = UiCommands()
            from .display import DisplayPipeline
            pipeline = DisplayPipeline(width,height,fps)
            pipeline.start()
            source = pipeline.frames(seconds)
            first_live_frame = next(source)
            print('Live screen first IDR ready: {} bytes'.format(sum(map(len,first_live_frame[1]))),flush=True)
        # Start the session before adding streams. HSAE starts audio receive
        # workers from SETUP only when the session's started flag is already set;
        # RECORD after stream SETUP starts ALSA but leaves the UDP queue unread.
        status,_,_ = client.request('RECORD','/')
        print('Demo RECORD before stream SETUP status={}'.format(status),flush=True)
        if status!=200:
            raise RuntimeError('media RECORD rejected')
        payload = {'streams':[{'type':110,'streamConnectionID':stream_id,'latencyMs':100,'uuid':display['uuid']}]}
        if live:
            from .audio import AudioSender
            audio=AudioSender(client,shared,info)
            if bluetooth_address and 'honda' not in str(info.get('model','')).lower():
                disable_bluetooth(client,bluetooth_address)
            elif bluetooth_address:
                # The HU needs its Bluetooth link for iAP2 call/media control.
                # Asking a Honda to disable it ends CarPlay after the next
                # accessory timeout and removes the wireless CarPlay record.
                print('Keeping accessory Bluetooth enabled for {}'.format(
                    info.get('model')),flush=True)
        status,_,body = client.request('SETUP','/setup',plistlib.dumps(payload,fmt=plistlib.FMT_BINARY),
            {'Content-Type':'application/x-apple-binary-plist'})
        print('Demo screen SETUP status={}'.format(status),flush=True)
        if status!=200:
            raise RuntimeError('media SETUP rejected')
        response = plistlib.loads(body)
        print('Demo screen response={}'.format(response),flush=True)
        stream = next(s for s in response['streams'] if s['type']==110)
        video = connect(address,int(stream['dataPort']),interface).sock
        if audio:
            audio.prepare()
            # Phone is the resource arbiter: it asserts ownership using modesChanged.
            # changeModes requests travel from the head unit to the phone.
            request={'type':'modesChanged','params':modes}
            mode_status,_,mode_body=client.request('POST','/command',plistlib.dumps(request,fmt=plistlib.FMT_BINARY),
                                      {'Content-Type':'application/x-apple-binary-plist'})
            print('Audio resource request status={}'.format(mode_status),flush=True)
            if mode_status!=200 or (mode_body and plistlib.loads(mode_body).get('status',0)!=0):
                raise RuntimeError('HU did not grant audio resource')
            audio_status,_,audio_body=client.request('SETUP','/setup',
                plistlib.dumps({'streams':[audio.description()]},fmt=plistlib.FMT_BINARY),
                {'Content-Type':'application/x-apple-binary-plist'})
            print('Audio SETUP after capture ready/resource claim status={}'.format(audio_status),flush=True)
            if audio_status!=200:raise RuntimeError('audio SETUP rejected')
            audio_stream=next(s for s in plistlib.loads(audio_body)['streams'] if s['type']==audio.description()['type'])
            audio.start(audio_stream,client.sock.sock.getpeername())
            if media:media.started()
        encoder = ScreenEncoder(shared,stream_id)
        if live:
            from .screenstream import ScreenStream
            screen=ScreenStream(client,address,interface,shared,display,video,stream_id,width,height,
                                request_keyframe=pipeline.request_keyframe)
            feedback=ScreenFeedback(client,commands,modes,resume,screen,resource_changed,audio,duck,mode_lock,mode_revision)
        if live:
            import itertools
            source = itertools.chain([first_live_frame],source)
        else:
            source = ((config,nals) for nals in frames[:seconds*30])
        start = time.monotonic()
        last_keepalive = start
        count = 0
        previous_config = None
        sample = open('/tmp/sailplay-live-video.h264','wb') if live else None
        for config,nals in source:
            if audio and audio.stop.is_set():
                print('Audio stream ended; continuing screen-only projection',flush=True)
                ended_audio, audio = audio, None
            if events and events.stop.is_set():
                raise RuntimeError('touch/event channel ended; reconnecting media session')
            if feedback and feedback.stop.is_set():
                raise RuntimeError('control feedback ended')
            if on_activity:
                on_activity()
            if live and not screen.send(config,nals,time.monotonic_ns()):
                continue
            if config!=previous_config:
                if sample:
                    sps_size=int.from_bytes(config[6:8],'big')
                    sps=config[8:8+sps_size]
                    pps_pos=9+sps_size
                    pps_size=int.from_bytes(config[pps_pos:pps_pos+2],'big')
                    sample.write(b'\x00\x00\x00\x01'+sps+b'\x00\x00\x00\x01'+config[pps_pos+2:pps_pos+2+pps_size])
                    sample.flush()
                if not live:
                    video.sendall(encoder.config(config,width,height,time.monotonic_ns()))
                previous_config=config
                print('Screen configuration sent: {} bytes'.format(len(config)),flush=True)
            delay = 0 if live else start+count/30-time.monotonic()
            if delay>0:
                time.sleep(delay)
            if sample and count<60:
                sample.write(b''.join(b'\x00\x00\x00\x01'+n for n in nals))
                sample.flush()
            packet=encoder.frame(nals,time.monotonic_ns(),width,height) if not live else None
            before=time.monotonic()
            try:
                if not live:
                    video.sendall(packet)
            except Exception as error:
                print('VIDEO failed t={:.3f} frame={} error={}'.format(time.monotonic(),count,type(error).__name__),flush=True)
                raise
            count+=1
            if count==1:
                print('Screen first IDR sent',flush=True)
            now=time.monotonic()
            if not live and now-last_keepalive>=1:
                video.sendall(struct.pack('<IB',0,2)+bytes(123))
                last_keepalive=now
            if count%300==0:
                print('Demo video sent {} frames in {:.2f}s'.format(count,time.monotonic()-start),flush=True)
        print('Demo complete: {} frames'.format(count),flush=True)
    finally:
        if iap_tunnel:
            iap_tunnel.close()
        if media:media.close()
        if power:
            power.close()
        if audio:
            audio.close()
        if ended_audio:
            ended_audio.close()
        if 'sample' in locals() and sample:
            sample.close()
        if feedback:
            feedback.close()
        if screen:
            screen.close()
        if commands:
            commands.close()
        if pipeline:
            pipeline.close()
        if video:
            video.close()
        if events:
            events.close()
        if touch:
            touch.close()
        try:
            client.request('TEARDOWN','/')
        except Exception:
            pass
