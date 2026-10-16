"""Streaming AAC-LC encoding. ADTS is local framing only, never RTP payload."""
import os
import select
import subprocess
import threading
import time
import array

class AdtsReader:
    def __init__(self,stream):self.stream=stream;self.buffer=bytearray()
    def frame(self,timeout=10):
        end=time.monotonic()+timeout
        while True:
            if len(self.buffer)>=7:
                b=self.buffer
                if b[0]!=255 or b[1]&246!=240:raise ValueError('invalid ADTS sync')
                if (b[2]>>2)&15!=3 or ((b[2]&1)<<2 | b[3]>>6)!=2:
                    raise ValueError('AAC must be 48kHz stereo')
                if (b[2]>>6)!=1 or b[6]&3:raise ValueError('AAC-LC single raw block required')
                size=((b[3]&3)<<11)|(b[4]<<3)|(b[5]>>5)
                header=7 if b[1]&1 else 9
                if size<=header:raise ValueError('invalid AAC frame length')
                if len(b)>=size:
                    payload=bytes(b[header:size]);del b[:size];return payload
            remaining=end-time.monotonic()
            if remaining<=0:raise TimeoutError('AAC encoder output timeout')
            if not select.select([self.stream],[],[],min(.2,remaining))[0]:continue
            data=os.read(self.stream.fileno(),16384)
            if not data:raise EOFError('AAC encoder ended')
            self.buffer.extend(data)

class AacCapture:
    def __init__(self,source,stop,gain):
        self.source=source;self.stop=stop;self.gain=gain;self.peak=0;self.error=None
        self.process=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error',
            '-f','s16le','-ar','48000','-ac','2','-probesize','32','-analyzeduration','0',
            '-i','pipe:0','-c:a','aac','-profile:a','aac_low','-b:a','256k',
            '-flush_packets','1','-f','adts','pipe:1'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        self.underrun_frames=0;self.dropped_frames=0
        self.log_thread=threading.Thread(target=self.log_errors,daemon=True);self.log_thread.start()
        self.reader=AdtsReader(self.process.stdout)
        self.thread=threading.Thread(target=self.feed,daemon=True);self.thread.start()
    def log_errors(self):
        for line in self.process.stderr:
            print('AAC encoder: '+line.decode(errors='replace').strip()[:1024],flush=True)
    def feed(self):
        pending=b'';deadline=None
        self.underrun_frames=0;self.dropped_frames=0
        try:
            while not self.stop.is_set():
                if deadline is None:
                    if not select.select([self.source],[],[],.2)[0]:continue
                    data=os.read(self.source.fileno(),16384)
                    if not data:raise EOFError('PCM capture ended')
                    pending+=data;deadline=time.monotonic()+.1
                # A steady sample clock must survive paused/suspended PA sinks.
                # Read until the next encoder tick, padding gaps with silence.
                while not self.stop.is_set():
                    remaining=deadline-time.monotonic()
                    if remaining<=0:break
                    if select.select([self.source],[],[],remaining)[0]:
                        data=os.read(self.source.fileno(),16384)
                        if not data:raise EOFError('PCM capture ended')
                        pending+=data
                        if len(pending)>48000:
                            excess=(len(pending)-48000)//4*4
                            pending=pending[excess:];self.dropped_frames+=excess//4
                if self.stop.is_set():break
                size=min(4096,len(pending)//4*4)
                data,pending=pending[:size],pending[size:]
                if len(data)<4096:
                    self.underrun_frames+=(4096-len(data))//4
                    data+=bytes(4096-len(data))
                samples=array.array('h');samples.frombytes(data)
                self.peak=max(self.peak,max(map(abs,samples),default=0))
                gain=self.gain()
                if gain!=1:samples=array.array('h',(int(v*gain) for v in samples))
                view=memoryview(samples.tobytes())
                while view:
                    n=os.write(self.process.stdin.fileno(),view);view=view[n:]
                deadline+=1024/48000
                if deadline<time.monotonic()-.1:deadline=time.monotonic()
        except Exception as error:
            if not self.stop.is_set():self.error=error
        finally:
            try:self.process.stdin.close()
            except OSError:pass
    def close(self):
        self.process.terminate()
        try:self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.thread.join(1)
        self.process.stdout.close()
        self.log_thread.join(1);self.process.stderr.close()
