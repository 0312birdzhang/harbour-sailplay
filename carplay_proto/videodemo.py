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

    def config(self, avcc, width, height):
        header = bytearray(128)
        struct.pack_into('<I',header,0,len(avcc))
        header[4], header[6] = 1,4
        struct.pack_into('<ff',header,16,width,height)
        return bytes(header)+avcc

    def frame(self, nals, timestamp_ns):
        body = b''.join(struct.pack('>I',len(n))+n for n in nals)
        header = bytearray(128)
        struct.pack_into('<I',header,0,len(body)+16)
        seconds, fraction = divmod(timestamp_ns,1000000000)
        struct.pack_into('<Q',header,8,(seconds << 32) | (fraction << 32)//1000000000)
        encrypted = self.native.seal(crypto.nonce64(self.counter),body,bytes(header))
        self.counter += 1
        return bytes(header)+encrypted


class DemoEvents:
    def __init__(self,address,port,interface,shared,handler=None):
        self.handler=handler
        transport = connect(address,port,interface)
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
                        return
                    buf += block
                body,buf = buf[:size],buf[size:]
                print('Demo event: {} bytes={}'.format(lines[0],size),flush=True)
                code=200
                reply=b''
                if body:
                    try:
                        value = plistlib.loads(body)
                        print('Demo event keys={}'.format(sorted(value)),flush=True)
                        print('Event command type={}'.format(value.get('type')),flush=True)
                        if self.handler and lines[0].split()[1]=='/command':
                            result=self.handler(value)
                            if result is not None:
                                reply=plistlib.dumps(result,fmt=plistlib.FMT_BINARY)
                    except Exception:
                        code=400
                self.sock.sendall(('RTSP/1.0 {} {}\r\nCSeq: {}\r\nContent-Type: application/x-apple-binary-plist\r\nContent-Length: {}\r\n\r\n'.format(
                    code,'OK' if code==200 else 'Bad Request',headers.get('cseq','0').strip(),len(reply))).encode()+reply)
        except Exception as error:
            if not self.stop.is_set():
                print('Demo event channel: {}'.format(type(error).__name__),flush=True)

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
    def __init__(self,client,commands=None,modes=None,resume=None,screen=None):
        self.client=client
        self.commands=commands
        self.modes=modes
        self.resume=resume
        self.screen=screen
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        next_feedback=time.monotonic()+2
        while not self.stop.wait(0.1):
            try:
                returning=self.commands and self.commands.return_requested()
                resuming=(self.resume is not None and self.resume.is_set()) or (self.commands and self.commands.resume.is_set())
                if returning or resuming:
                    if resuming:
                        if self.resume is not None:
                            self.resume.clear()
                        if self.commands:
                            self.commands.resume.clear()
                    print('Screen ownership command: {}'.format('CarPlay' if resuming else 'OEM'),flush=True)
                    proposed=copy.deepcopy(self.modes)
                    screen=next(r for r in proposed['resources'] if r['resourceID']==1)
                    owner=1 if resuming else 2
                    screen.update(entity=owner,permanentEntity=owner)
                    payload=plistlib.dumps({'type':'modesChanged','params':proposed},fmt=plistlib.FMT_BINARY)
                    status,_,body=self.client.request('POST','/command',payload,
                        {'Content-Type':'application/x-apple-binary-plist'})
                    command_status=plistlib.loads(body).get('status',0) if body else 0
                    accepted=status==200 and command_status==0
                    if accepted:
                        next(r for r in self.modes['resources'] if r['resourceID']==1).update(entity=owner,permanentEntity=owner)
                        if self.screen:
                            self.screen.ownership(owner)
                    print('Screen ownership response owner={} status={} command_status={} accepted={}'.format(owner,status,command_status,accepted),flush=True)
                if time.monotonic()<next_feedback:
                    continue
                status,_,body=self.client.request('POST','/feedback',headers={'User-Agent':'AirPlay/566.25.21'})
                next_feedback=time.monotonic()+2
                print('Screen feedback status={} bytes={}'.format(status,len(body)),flush=True)
            except Exception as error:
                print('Screen feedback failed: {}'.format(type(error).__name__),flush=True)
                self.stop.set()
                return

    def close(self):
        self.stop.set()
        self.thread.join(6)


def run_demo(client,address,interface,shared,setup_info,info,path=None,seconds=15,live=False,on_activity=None):
    display = info['displays'][0]
    pipeline = None
    if not live:
        with open(path,'rb') as demo_file:
            config,frames = demo_frames(demo_file.read())
    if (int(display['widthPixels']),int(display['heightPixels'])) != (1920,720):
        raise ValueError('demo requires 1920x720 display')
    stream_id = int.from_bytes(__import__('os').urandom(7),'big') or 1
    touch = audio = None
    resume = threading.Event()
    modes={'appStates':[{'appStateID':1,'entity':0,'speechMode':-1},
                        {'appStateID':2,'entity':0},{'appStateID':3,'entity':0}],
           'resources':[{'resourceID':r,'entity':1,'permanentEntity':1} for r in (1,2)]}
    def event_command(value):
        if touch:
            touch.command(value)
        if value.get('type')=='requestUI':
            resume.set()
            return {'status':0}
        if value.get('type')=='changeModes':
            for request in value.get('params',{}).get('resources',[]):
                resource=next((r for r in modes['resources'] if r['resourceID']==request.get('resourceID')),None)
                if resource is not None:
                    transfer=request.get('transferType')
                    if transfer in (1,3): resource['entity']=2
                    elif transfer in (2,4): resource['entity']=1
                    if transfer in (1,2):resource['permanentEntity']=resource['entity']
                    if resource['resourceID']==1 and resource['entity']==1:
                        resume.set()
            if audio:
                audio.gain=1.0 if modes['resources'][1]['entity']==1 else 0.0
            print('HU mode request applied: {}'.format(modes['resources']),flush=True)
            return {'status':0,'params':modes}
        if audio and value.get('type') in ('duckAudio','unduckAudio'):
            volume=max(-144,min(0,float(value.get('params',{}).get('volume',0))))
            audio.gain=10**(volume/20) if value['type']=='duckAudio' else 1.0
    if live:
        from .touch import TouchInput
        touch=TouchInput(info.get('hidDevices',[]),display['uuid'])
    events = None
    video = None
    feedback = None
    commands = None
    screen = None
    try:
        events = DemoEvents(address,int(setup_info['eventPort']),interface,shared,
                            event_command)
        first_live_frame = None
        if live:
            commands = UiCommands()
            from .display import DisplayPipeline
            pipeline = DisplayPipeline()
            pipeline.start()
            source = pipeline.frames(seconds)
            first_live_frame = next(source)
            print('Live screen first IDR ready: {} bytes'.format(sum(map(len,first_live_frame[1]))),flush=True)
        payload = {'streams':[{'type':110,'streamConnectionID':stream_id,'latencyMs':100,'uuid':display['uuid']}]}
        if live:
            from .audio import AudioSender
            audio=AudioSender(client,shared,info)
            payload['streams'].append(audio.description())
        status,_,body = client.request('SETUP','/setup',plistlib.dumps(payload,fmt=plistlib.FMT_BINARY),
            {'Content-Type':'application/x-apple-binary-plist'})
        print('Demo screen SETUP status={}'.format(status),flush=True)
        if status!=200:
            raise RuntimeError('media SETUP rejected')
        response = plistlib.loads(body)
        print('Demo screen response={}'.format(response),flush=True)
        stream = next(s for s in response['streams'] if s['type']==110)
        video = connect(address,int(stream['dataPort']),interface).sock
        status,_,_ = client.request('RECORD','/')
        print('Demo RECORD status={}'.format(status),flush=True)
        if status!=200:
            raise RuntimeError('media RECORD rejected')
        if audio:
            audio_stream=next(s for s in response['streams'] if s['type']==100)
            # Phone is the resource arbiter: it asserts ownership using modesChanged.
            # changeModes requests travel from the head unit to the phone.
            request={'type':'modesChanged','params':modes}
            mode_status,_,mode_body=client.request('POST','/command',plistlib.dumps(request,fmt=plistlib.FMT_BINARY),
                                      {'Content-Type':'application/x-apple-binary-plist'})
            print('Audio resource request status={}'.format(mode_status),flush=True)
            if mode_status!=200 or (mode_body and plistlib.loads(mode_body).get('status',0)!=0):
                raise RuntimeError('HU did not grant audio resource')
            audio.start(audio_stream,client.sock.sock.getpeername())
        encoder = ScreenEncoder(shared,stream_id)
        if live:
            from .screenstream import ScreenStream
            screen=ScreenStream(client,address,interface,shared,display,video,stream_id)
            feedback=ScreenFeedback(client,commands,modes,resume,screen)
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
                    video.sendall(encoder.config(config,1920,720))
                previous_config=config
                print('Screen configuration sent: {} bytes'.format(len(config)),flush=True)
            delay = 0 if live else start+count/30-time.monotonic()
            if delay>0:
                time.sleep(delay)
            if sample and count<60:
                sample.write(b''.join(b'\x00\x00\x00\x01'+n for n in nals))
                sample.flush()
            packet=encoder.frame(nals,time.monotonic_ns()) if not live else None
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
        if audio:
            audio.close()
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
