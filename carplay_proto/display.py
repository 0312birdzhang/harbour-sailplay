"""Own a temporary Sailife compositor/UI/capture pipeline for CarPlay."""
import os
import fcntl
import select
import signal
import subprocess
import time



def child_pids(parent, proc='/proc'):
    """Direct children of parent.

    Uses /proc/PID/task/PID/children when the kernel provides it
    (CONFIG_PROC_CHILDREN); otherwise scans the PPid field of every
    /proc/*/stat, which works on any kernel.
    """
    try:
        with open('{0}/{1}/task/{1}/children'.format(proc, parent)) as source:
            return [int(pid) for pid in source.read().split()]
    except FileNotFoundError:
        pass
    children = []
    for name in os.listdir(proc):
        if not name.isdigit():
            continue
        try:
            with open('{}/{}/stat'.format(proc, name)) as source:
                stat = source.read()
        except OSError:
            continue
        # The command name may contain spaces or parentheses; PPid is the
        # second field after its closing parenthesis.
        fields = stat.rsplit(')', 1)[-1].split()
        if len(fields) > 1 and fields[1] == str(parent):
            children.append(int(name))
    return sorted(children)

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


def projected_apps(proc='/proc'):
    """PID/start-time pairs belonging exclusively to our virtual Wayland output.

    A detached Qt client can outlive its compositor. Require both the output
    and launcher marker; never infer ownership from its executable name.
    """
    result = {}
    for name in os.listdir(proc):
        if not name.isdigit():
            continue
        base = '{}/{}'.format(proc, name)
        try:
            with open(base + '/environ', 'rb') as source:
                env = dict(v.split(b'=', 1) for v in source.read().split(b'\0') if b'=' in v)
            if (env.get(b'WAYLAND_DISPLAY') != b'imira-comp-0'
                    or not env.get(b'CARLIFE_APP_KEY')
                    or env.get(b'CARLIFE_APP_KEY') == b'sailplay-input-method'):
                continue
            with open(base + '/stat') as source:
                stat = source.read().rsplit(')', 1)[-1].split()
            if stat[0] != 'Z':
                result[int(name)] = stat[19]
        except (OSError, ValueError, IndexError):
            continue
    return result


def stop_projected_apps(grace=2):
    """Stop detached projected clients while the caller owns the display lock."""
    owned = projected_apps()
    for pid, started in owned.items():
        if projected_apps().get(pid) != started:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            print('Projection app cleanup TERM pid={}'.format(pid), flush=True)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace
    pending = owned
    while pending and time.monotonic() < deadline:
        current = projected_apps()
        pending = {pid:started for pid,started in owned.items() if current.get(pid) == started}
        if pending:
            time.sleep(.05)
    current = projected_apps()
    for pid, started in pending.items():
        if current.get(pid) != started:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            print('Projection app cleanup KILL pid={}'.format(pid), flush=True)
        except ProcessLookupError:
            pass


class DisplayPipeline:
    def __init__(self,width=1920,height=720,fps=30):
        self.width,self.height,self.fps=width,height,fps
        self.processes=[]
        self.logs=[]
        self.ui=None
        self.comp=None
        self.fd=None
        self.lock_fd=None
        self.fifo='/tmp/sailplay-display-{}.h264'.format(os.getpid())

    def launch(self,name,command):
        log=open('/home/defaultuser/sailplay-{}.log'.format(name),'ab')
        log.write(('\nSailplay launch {} at {}\n'.format(name,time.time())).encode());log.flush()
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
        # Recover detached clients left by a previous crashed display session.
        stop_projected_apps()
        if not os.path.exists('/run/display/wayland-0'):
            raise RuntimeError('lipstick display unavailable')
        os.mkfifo(self.fifo,0o666)
        os.chmod(self.fifo,0o666)
        self.fd=os.open(self.fifo,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
        comp=self.comp=self.launch('comp','env XDG_RUNTIME_DIR=/run/user/100000 WAYLAND_DISPLAY=../../display/wayland-0 '
                         '/opt/sailplay/imira-comp --width {} --height {} --fps {}'.format(self.width,self.height,self.fps))
        deadline=time.monotonic()+8
        while not os.path.exists('/run/user/100000/imira-comp-0'):
            if comp.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('virtual compositor failed to start')
            time.sleep(.1)
        keyboard=self.launch('keyboard','env XDG_RUNTIME_DIR=/run/user/100000 '
                    'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket '
                    'python3 /opt/sailplay/scripts/keyboard-server.py')
        deadline=time.monotonic()+8
        while not os.path.exists('/run/user/100000/sailplay-maliit/socket'):
            if keyboard.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('private keyboard failed to start')
            time.sleep(.1)
        self.ui=self.launch('carui','env XDG_RUNTIME_DIR=/run/user/100000 '
                    'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket '
                    'QT_QPA_PLATFORM=wayland '
                    'WAYLAND_DISPLAY=imira-comp-0 /opt/sailplay/carui/carui /opt/sailplay/carui/main.qml {} {}'.format(self.width,self.height))
        self.capture=self.launch('capture','env XDG_RUNTIME_DIR=/run/user/100000 /opt/sailplay/carlife-capture '
                    '--input shm --out '+self.fifo+' --width {} --height {} --fps {} --bitrate {}'.format(
                        self.width,self.height,self.fps,4000000*self.fps//30))
        print('Sailife virtual UI/capture started; dedicated CarPlay FIFO',flush=True)
        return self

    def check_health(self):
        for name,process in (('compositor',self.comp),('carui',self.ui)):
            if process is not None and process.poll() is not None:
                raise RuntimeError('{} exited status={}; rebuilding display session'.format(name,process.returncode))

    def request_keyframe(self):
        # su remains as a parent; never signal the entire group, which would
        # also terminate su. Validate the executable and this pipeline's FIFO.
        parent = self.capture.pid
        if not os.path.exists('/proc/{}'.format(parent)):
            raise RuntimeError('capture process exited before keyframe request')
        candidates = [parent] + child_pids(parent)
        for pid in candidates:
            try:
                executable = os.readlink('/proc/{}/exe'.format(pid))
                if executable != '/opt/sailplay/carlife-capture':
                    continue
                with open('/proc/{}/cmdline'.format(pid), 'rb') as source:
                    arguments = source.read().split(b'\0')
                if self.fifo.encode() in arguments:
                    os.kill(pid, signal.SIGUSR1)
                    return
            except FileNotFoundError:
                continue
        raise RuntimeError('owned capture process not found for keyframe request')

    def frames(self,seconds):
        parser=AnnexBFrames()
        deadline=time.monotonic()+seconds if seconds else float('inf')
        last_data=time.monotonic()
        while time.monotonic()<deadline:
            self.check_health()
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
        # Keep compositor and session bus alive for Qt/location teardown first.
        if self.comp is not None and self.lock_fd is not None:
            stop_projected_apps()
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
        self.processes = []
        self.comp = self.ui = self.capture = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        for log in self.logs:
            log.close()
        self.logs = []
        if os.path.exists(self.fifo):
            os.unlink(self.fifo)
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd=None
