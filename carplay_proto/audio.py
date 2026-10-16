"""48 kHz stereo playback over CarPlay's encrypted RTP audio stream."""
import array
import logging
import os
import select
import signal
import socket
import struct
import subprocess
import threading
import time
from . import crypto
from .nativecrypto import NativeChaCha

# Receiver protocol compatibility build, not the Sailfish OS release.
# The HSAE receiver compares 13A1 against this %d%c%d value to choose
# timestamp+SSRC (8-byte) RTP AAD. "5.2" compares older and selects 12-byte AAD.
AUDIO_COMPAT_BUILD = '13A344'


class AudioEncoder:
    def __init__(self,shared,stream_id):
        key=crypto.hkdf_sha512(shared,('DataStream-Salt'+str(stream_id)).encode(),b'DataStream-Output-Encryption-Key',32)
        self.cipher=NativeChaCha(key);self.counter=0;self.sequence=0;self.timestamp=0
    def packet(self,pcm_le):
        if len(pcm_le)%4:raise ValueError('unaligned stereo PCM')
        pcm=array.array('h');pcm.frombytes(pcm_le)
        if __import__('sys').byteorder=='little':pcm.byteswap()
        return self.encoded_packet(pcm.tobytes(),100,len(pcm_le)//4)
    def encoded_packet(self,data,payload_type=96,samples=1024):
        header=struct.pack('>BBHII',128,payload_type,self.sequence,self.timestamp,0)
        nonce=self.counter.to_bytes(8,'little')
        payload=self.cipher.seal(bytes(4)+nonce,data,header[4:12])
        self.sequence=(self.sequence+1)&65535;self.timestamp=(self.timestamp+samples)&0xffffffff;self.counter+=1
        return header+payload+nonce


class AudioSender:
    def __init__(self,client,shared,info):
        self.aac=any(int(f.get('type',0))==102 and f.get('audioType')=='media' and int(f.get('audioOutputFormats',0))&8388608 for f in info.get('audioFormats',[]))
        self.aac_capture=None
        supported=any(int(f.get('type',0))==100 and f.get('audioType')=='media' and int(f.get('audioOutputFormats',0))&32768
                      for f in info.get('audioFormats',[]))
        if not supported and not self.aac:raise ValueError('HU does not advertise PCM 48000 stereo on main audio')
        tcp=client.sock.sock
        self.sock=socket.socket(tcp.family,socket.SOCK_DGRAM)
        local=list(tcp.getsockname());local[1]=0;self.sock.bind(tuple(local));self.sock.settimeout(.5)
        self.control=socket.socket(tcp.family,socket.SOCK_DGRAM);self.control.bind(tuple(local))
        self.stream_id=int.from_bytes(os.urandom(7),'big') or 1
        self.encoder=AudioEncoder(shared,self.stream_id)
        self.stop=threading.Event();self.thread=None;self.process=None;self.log=None;self.log_thread=None
        self.gain=1.0
        self.receiver_info=info
    def description(self):
        return {'type':102 if self.aac else 100,'streamConnectionID':self.stream_id,'audioFormat':8388608 if self.aac else 32768,'audioType':'media',
                'audioLatencyMs':1000 if self.aac else 100,'ct':4 if self.aac else 1,'sr':48000,'ch':2,'input':False,'controlPort':self.control.getsockname()[1],
                'spf':1024 if self.aac else 352}
    def start(self,response,peer):
        if int(response.get('streamConnectionID',self.stream_id))!=self.stream_id:raise ValueError('audio stream ID mismatch')
        dest=list(peer);dest[1]=int(response['dataPort']);self.sock.connect(tuple(dest))
        print('Audio negotiated codec={} streamType={} RTPtype={}'.format('AAC-LC' if self.aac else 'PCM',102 if self.aac else 100,96 if self.aac else 100),flush=True)
        print('Audio transport peer={} dataPort={} receiverControlPort={} senderControlPort={} AADbytes=8 streamConnectionID={} receiverStreamConnectionID={}'.format(
            peer[0], response['dataPort'], response.get('controlPort'), self.control.getsockname()[1],
            self.stream_id, response.get('streamConnectionID')), flush=True)
        if self.process is None:self.prepare()
        self.thread=threading.Thread(target=self.run_aac if self.aac else self.run,daemon=True);self.thread.start()
        print('Audio RTP sender started: {} 48000Hz stereo encrypted spf={}'.format('AAC-LC' if self.aac else 'PCM',1024 if self.aac else 352),flush=True)
    def prepare(self,timeout=10):
        """Wait for actual PCM before the receiver starts its audio resource."""
        if self.process is not None:return
        started=time.monotonic()
        avoid_diplay_audio_loop(self.receiver_info)
        from .runtime_logging import private_handler
        self.log=private_handler('audio-capture')
        self.process=subprocess.Popen(['su','defaultuser','-s','/bin/sh','-c',
          'exec env XDG_RUNTIME_DIR=/run/user/100000 python3 /opt/sailplay/scripts/pulse-capture.py'],
          stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        self.log_thread=threading.Thread(target=self.capture_log,daemon=True);self.log_thread.start()
        if self.aac:
            from .aac import AacCapture
            self.aac_capture=AacCapture(self.process.stdout,self.stop,lambda:self.gain)
            while True:
                self.initial_aac=self.aac_capture.reader.frame(max(.1,timeout-(time.monotonic()-started)))
                if time.monotonic()-started>=4:break
            print('AAC capture/encoder ready elapsedMs={:.1f} bytes={}'.format((time.monotonic()-started)*1000,len(self.initial_aac)),flush=True)
            return
        self.initial_pcm=b''
        while True:
            now=time.monotonic()
            remaining=timeout-(now-started)
            if remaining<=0:raise TimeoutError('audio capture did not become ready')
            ready,_,_=select.select([self.process.stdout],[],[],min(.2,remaining))
            if not ready:continue
            data=os.read(self.process.stdout.fileno(),16384)
            if not data:raise EOFError('audio capture ended before ready')
            now=time.monotonic()
            # Discard warm-up PCM; retain only one fresh packet, never seconds
            # of old playback while Bluetooth profiles and PA routes settle.
            self.initial_pcm=(self.initial_pcm+data)[-1408:]
            if now-started>=4 and len(self.initial_pcm)==1408:break
        print('Audio capture ready elapsedMs={:.1f} bufferedFrames={}'.format(
            (time.monotonic()-started)*1000,len(self.initial_pcm)//4),flush=True)

    def capture_log(self):
        for raw in iter(self.process.stderr.readline,b''):
            line=raw.decode('utf-8',errors='replace').rstrip()[:16384]
            if self.log:
                self.log.handle(logging.LogRecord('audio-capture',logging.INFO,'',0,line,(),None))
            else:
                print('Audio capture: '+line,flush=True)
    def run(self):
        buf=getattr(self,'initial_pcm',b'');count=0;deadline=time.monotonic();last=time.monotonic();peak=0;capture_peak=0
        last_read=last;last_send=None;read_gap=send_gap=0;resets=0
        try:
            while not self.stop.is_set():
                if len(buf)<1408:
                    ready,_,_=select.select([self.process.stdout],[],[],.2)
                    if not ready:continue
                    data=os.read(self.process.stdout.fileno(),16384)
                    if not data:raise EOFError('playback capture ended')
                    now=time.monotonic();read_gap=max(read_gap,now-last_read);last_read=now
                    buf+=data
                while len(buf)>=1408 and not self.stop.is_set():
                    chunk,buf=buf[:1408],buf[1408:]
                    samples=array.array('h');samples.frombytes(chunk)
                    capture_peak=max(capture_peak,max(map(abs,samples),default=0))
                    gain=self.gain
                    if gain!=1:
                        samples=array.array('h',(int(sample*gain) for sample in samples))
                        chunk=samples.tobytes()
                    peak=max(peak,max(map(abs,samples),default=0))
                    now=time.monotonic()
                    if deadline<now-.1:deadline=now;resets+=1
                    if self.stop.wait(max(0,deadline-now)):break
                    self.sock.send(self.encoder.packet(chunk))
                    sent=time.monotonic()
                    if last_send is not None:send_gap=max(send_gap,sent-last_send)
                    last_send=sent;deadline+=352/48000;count+=1
                    if time.monotonic()-last>=10:
                        print('Audio RTP packets={} peak={} capturePeak={} senderGain={} captureGapMs={:.1f} sendGapMs={:.1f} pacingResets={} bufferedFrames={}'.format(
                            count,peak,capture_peak,gain,read_gap*1000,send_gap*1000,resets,len(buf)//4),flush=True)
                        last=time.monotonic();peak=capture_peak=0;read_gap=send_gap=0;resets=0
        except Exception as error:
            if not self.stop.is_set():print('Audio sender failed: '+type(error).__name__,flush=True)
            self.stop.set()
    def run_aac(self):
        count=0;last=time.monotonic();deadline=last;previous=None;gap=0
        try:
            frame=self.initial_aac
            while not self.stop.is_set():
                if self.aac_capture.error:raise self.aac_capture.error
                now=time.monotonic()
                if deadline<now-.1:deadline=now
                if self.stop.wait(max(0,deadline-now)):break
                self.sock.send(self.encoder.encoded_packet(frame))
                sent=time.monotonic()
                if previous is not None:gap=max(gap,sent-previous)
                previous=sent;deadline+=1024/48000;count+=1
                if sent-last>=10:
                    print('Audio AAC RTP packets={} capturePeak={} senderGain={} sendGapMs={:.1f} framesPerPacket=1024 RTPtype=96 silenceFrames={} droppedFrames={}'.format(count,self.aac_capture.peak,self.gain,gap*1000,self.aac_capture.underrun_frames,self.aac_capture.dropped_frames),flush=True)
                    last=sent;gap=0;self.aac_capture.peak=0
                frame=self.aac_capture.reader.frame()
        except Exception as error:
            if not self.stop.is_set():print('AAC sender failed: {} {}'.format(type(error).__name__,error),flush=True)
            self.stop.set()

    def close(self):
        self.stop.set()
        if self.aac_capture:self.aac_capture.close()
        if self.process:
            try:os.killpg(self.process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            # Closing the reader also releases a helper blocked writing PCM.
            if self.thread:self.thread.join(1)
            self.process.stdout.close()
            try:self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid,signal.SIGKILL);self.process.wait()
            if self.log_thread:self.log_thread.join(1)
            self.process.stderr.close()
        self.sock.close();self.control.close()
        if self.log:self.log.close()


def avoid_diplay_audio_loop(info):
    """Android receivers can route decoded media back to Sailfish's A2DP sink."""
    if str(info.get('model','')).lower() != 'diplay':
        return
    from .bluezadapter import previous_head_unit, authenticated_head_unit
    device=previous_head_unit()
    if not authenticated_head_unit(device):
        print('DiPlay audio loop guard skipped: no authenticated Bluetooth target',flush=True)
        return
    try:
        import dbus
        bus=dbus.SystemBus()
        obj=bus.get_object('org.bluez',device)
        props=dbus.Interface(obj,'org.freedesktop.DBus.Properties').GetAll('org.bluez.Device1')
        source='0000110a-0000-1000-8000-00805f9b34fb'
        if props.get('Connected') and source in list(map(str,props.get('UUIDs',[]))):
            dbus.Interface(obj,'org.bluez.Device1').DisconnectProfile(source,timeout=10)
            print('DiPlay A2DP audio return disconnected; CarPlay transport retained',flush=True)
    except Exception as error:
        print('DiPlay audio loop guard failed: {}'.format(type(error).__name__),flush=True)
