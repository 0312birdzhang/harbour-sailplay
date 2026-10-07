"""48 kHz stereo playback over CarPlay's encrypted RTP audio stream."""
import array
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


class AudioEncoder:
    def __init__(self,shared,stream_id):
        key=crypto.hkdf_sha512(shared,('DataStream-Salt'+str(stream_id)).encode(),b'DataStream-Output-Encryption-Key',32)
        self.cipher=NativeChaCha(key);self.counter=0;self.sequence=0;self.timestamp=0
    def packet(self,pcm_le):
        if len(pcm_le)%4:raise ValueError('unaligned stereo PCM')
        pcm=array.array('h');pcm.frombytes(pcm_le)
        if __import__('sys').byteorder=='little':pcm.byteswap()
        header=struct.pack('>BBHII',128,100,self.sequence,self.timestamp,0)
        nonce=self.counter.to_bytes(8,'little')
        payload=self.cipher.seal(bytes(4)+nonce,pcm.tobytes(),header[4:12])
        self.sequence=(self.sequence+1)&65535;self.timestamp=(self.timestamp+len(pcm_le)//4)&0xffffffff;self.counter+=1
        return header+payload+nonce


class AudioSender:
    def __init__(self,client,shared,info):
        supported=any(int(f.get('type',0))==100 and f.get('audioType')=='media' and int(f.get('audioOutputFormats',0))&32768
                      for f in info.get('audioFormats',[]))
        if not supported:raise ValueError('HU does not advertise PCM 48000 stereo on main audio')
        tcp=client.sock.sock
        self.sock=socket.socket(tcp.family,socket.SOCK_DGRAM)
        local=list(tcp.getsockname());local[1]=0;self.sock.bind(tuple(local));self.sock.settimeout(.5)
        self.control=socket.socket(tcp.family,socket.SOCK_DGRAM);self.control.bind(tuple(local))
        self.stream_id=int.from_bytes(os.urandom(7),'big') or 1
        self.encoder=AudioEncoder(shared,self.stream_id)
        self.stop=threading.Event();self.thread=None;self.process=None;self.log=None
        self.gain=1.0
    def description(self):
        return {'type':100,'streamConnectionID':self.stream_id,'audioFormat':32768,'audioType':'media',
                'audioLatencyMs':100,'input':False,'controlPort':self.control.getsockname()[1],
                'spf':352}
    def start(self,response,peer):
        if int(response.get('streamConnectionID',self.stream_id))!=self.stream_id:raise ValueError('audio stream ID mismatch')
        dest=list(peer);dest[1]=int(response['dataPort']);self.sock.connect(tuple(dest))
        self.log=open('/home/defaultuser/sailplay-audio.log','wb')
        self.process=subprocess.Popen(['su','defaultuser','-s','/bin/sh','-c',
          'exec env XDG_RUNTIME_DIR=/run/user/100000 python3 /opt/sailplay/scripts/pulse-capture.py'],
          stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=self.log,start_new_session=True)
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
        print('Audio RTP sender started: PCM 48000Hz stereo, encrypted, {} samples/packet'.format(352),flush=True)
    def run(self):
        buf=b'';count=0;deadline=time.monotonic();last=time.monotonic();peak=0
        try:
            while not self.stop.is_set():
                ready,_,_=select.select([self.process.stdout],[],[],.2)
                if not ready:continue
                data=os.read(self.process.stdout.fileno(),16384)
                if not data:raise EOFError('playback capture ended')
                buf+=data
                while len(buf)>=1408 and not self.stop.is_set():
                    chunk,buf=buf[:1408],buf[1408:]
                    samples=array.array('h');samples.frombytes(chunk);peak=max(peak,max(map(abs,samples),default=0))
                    if self.gain!=1:
                        chunk=array.array('h',(int(sample*self.gain) for sample in samples)).tobytes()
                    now=time.monotonic()
                    if deadline<now-.1:deadline=now
                    if self.stop.wait(max(0,deadline-now)):break
                    self.sock.send(self.encoder.packet(chunk));deadline+=352/48000;count+=1
                    if time.monotonic()-last>=10:
                        print('Audio RTP packets={} peak={}'.format(count,peak),flush=True);last=time.monotonic();peak=0
        except Exception as error:
            if not self.stop.is_set():print('Audio sender failed: '+type(error).__name__,flush=True)
            self.stop.set()
    def close(self):
        self.stop.set()
        if self.process:
            try:os.killpg(self.process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            # Closing the reader also releases a helper blocked writing PCM.
            if self.thread:self.thread.join(1)
            self.process.stdout.close()
            try:self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid,signal.SIGKILL);self.process.wait()
        self.sock.close();self.control.close()
        if self.log:self.log.close()
