"""Own a temporary Sailife compositor/UI/capture pipeline for CarPlay."""
import os
import fcntl
import select
import signal
import subprocess
import time


class AnnexBFrames:
    def __init__(self):
        self.buffer = b''
        self.sps = self.pps = None
        self.current = []
        self.started = False

    def feed(self,data):
        import re
        self.buffer += data
        if len(self.buffer)>8*1024*1024:
            raise ValueError('capture NAL exceeds limit')
        matches=list(re.finditer(b'\x00\x00\x00?\x01',self.buffer))
        frames=[]
        for left,right in zip(matches,matches[1:]):
            nal=self.buffer[left.end():right.start()]
            if not nal:
                continue
            kind=nal[0]&31
            if kind in (7,8):
                if kind==7:
                    self.sps=nal
                else:
                    self.pps=nal
            elif kind in (1,5):
                if len(nal)<2:
                    raise ValueError('truncated slice')
                if nal[1]&128 and self.current:
                    frames.append(self.current)
                    self.current=[]
                if kind==5 and self.sps and self.pps:
                    self.started=True
                if self.started:
                    self.current.append(nal)
        if matches:
            self.buffer=self.buffer[matches[-1].start():]
        return frames

    def config(self):
        import struct
        if not self.sps or not self.pps:
            raise ValueError('capture configuration missing')
        s,p=self.sps,self.pps
        return bytes([1,s[1],s[2],s[3],255,225])+struct.pack('>H',len(s))+s+b'\x01'+struct.pack('>H',len(p))+p


class DisplayPipeline:
    def __init__(self,width=1920,height=720,fps=30):
        self.width,self.height,self.fps=width,height,fps
        self.processes=[]
        self.logs=[]
        self.fd=None
        self.lock_fd=None
        self.fifo='/tmp/sailplay-display-{}.h264'.format(os.getpid())

    def launch(self,name,command):
        log=open('/home/defaultuser/sailplay-{}.log'.format(name),'wb')
        self.logs.append(log)
        process=subprocess.Popen(['su','defaultuser','-s','/bin/sh','-c','exec '+command],
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        self.processes.append(process)
        return process

    def start(self):
        # BusyBox pgrep -x matches argv, not the short executable name.
        # Serialize startup too: the compositor socket can appear before the
        # process check and a second compositor truncates the shared framebuffer.
        self.lock_fd=os.open('/run/sailplay-display.lock',os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(self.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.lock_fd)
            self.lock_fd=None
            raise RuntimeError('existing display pipeline active')
        if subprocess.run(['pgrep','-f',r'(^|/)imira-comp( |$)'],stdout=subprocess.DEVNULL).returncode==0:
            os.close(self.lock_fd)
            self.lock_fd=None
            raise RuntimeError('existing compositor active; refusing conflicting display pipeline')
        if not os.path.exists('/run/display/wayland-0'):
            raise RuntimeError('lipstick display unavailable')
        os.mkfifo(self.fifo,0o666)
        os.chmod(self.fifo,0o666)
        self.fd=os.open(self.fifo,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
        comp=self.launch('comp','env XDG_RUNTIME_DIR=/run/user/100000 WAYLAND_DISPLAY=../../display/wayland-0 '
                         '/opt/sailplay/imira-comp --width {} --height {} --fps {}'.format(self.width,self.height,self.fps))
        deadline=time.monotonic()+8
        while not os.path.exists('/run/user/100000/imira-comp-0'):
            if comp.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('virtual compositor failed to start')
            time.sleep(.1)
        self.launch('carui','env XDG_RUNTIME_DIR=/run/user/100000 '
                    'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket '
                    'QT_QPA_PLATFORM=wayland '
                    'WAYLAND_DISPLAY=imira-comp-0 /opt/sailplay/carui/carui /opt/sailplay/carui/main.qml {} {}'.format(self.width,self.height))
        self.capture=self.launch('capture','env XDG_RUNTIME_DIR=/run/user/100000 /opt/sailplay/carlife-capture '
                    '--input shm --out '+self.fifo+' --width {} --height {} --fps {} --bitrate {}'.format(
                        self.width,self.height,self.fps,4000000*self.fps//30))
        print('Sailife virtual UI/capture started; dedicated CarPlay FIFO',flush=True)
        return self

    def frames(self,seconds):
        parser=AnnexBFrames()
        deadline=time.monotonic()+seconds if seconds else float('inf')
        last_data=time.monotonic()
        while time.monotonic()<deadline:
            if self.capture.poll() is not None:
                raise RuntimeError('capture exited')
            ready,_,_=select.select([self.fd],[],[],.2)
            if ready:
                data=os.read(self.fd,65536)
                if not data:
                    time.sleep(.02)
                    continue
                last_data=time.monotonic()
                for frame in parser.feed(data):
                    yield parser.config(),frame
            if time.monotonic()-last_data>8:
                raise TimeoutError('capture produced no frames')

    def close(self):
        for process in reversed(self.processes):
            try:
                os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(.3)
        for process in reversed(self.processes):
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        if self.fd is not None:
            os.close(self.fd)
        for log in self.logs:
            log.close()
        if os.path.exists(self.fifo):
            os.unlink(self.fifo)
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd=None
