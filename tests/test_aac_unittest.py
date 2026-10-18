import io
import os
import struct
import subprocess
import unittest
from carplay_proto.aac import AdtsReader
from carplay_proto.audio import AudioEncoder
from carplay_proto import crypto

class AacTests(unittest.TestCase):
    def test_rtp_payload_and_timestamp_and_aead(self):
        shared=bytes(range(32));stream=123
        encoder=AudioEncoder(shared,stream)
        payload=bytes.fromhex('211004608c1c')
        a=encoder.encoded_packet(payload);b=encoder.encoded_packet(payload)
        self.assertEqual(struct.unpack('>BBHII',a[:12]),(128,96,0,0,0))
        self.assertEqual(struct.unpack('>BBHII',b[:12]),(128,96,1,1024,0))
        key=crypto.hkdf_sha512(shared,b'DataStream-Salt123',b'DataStream-Output-Encryption-Key',32)
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        self.assertEqual(ChaCha20Poly1305(key).decrypt(bytes(4)+a[-8:],a[12:-8],a[4:12]),payload)
    def test_real_encoder_adts_is_stripped_and_decodable(self):
        import shutil
        if not shutil.which('ffmpeg'):self.skipTest('ffmpeg unavailable')
        result=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=1000:sample_rate=48000',
            '-t','0.15','-ac','2','-c:a','aac','-profile:a','aac_low','-f','adts','pipe:1'],capture_output=True,check=True)
        decoded=subprocess.run(['ffmpeg','-v','error','-f','aac','-i','pipe:0','-f','s16le','pipe:1'],input=result.stdout,capture_output=True,check=True)
        self.assertGreater(len(decoded.stdout),4800)
        self.assertTrue(any(decoded.stdout))
        with __import__('tempfile').TemporaryFile() as f:
            f.write(result.stdout);f.seek(0)
            reader=AdtsReader(f);frame=reader.frame()
            self.assertGreater(len(frame),5)
            self.assertNotEqual(frame[:2],b'\xff\xf1')
    def test_invalid_header_rejected(self):
        with __import__('tempfile').TemporaryFile() as f:
            f.write(bytes(7));f.seek(0)
            with self.assertRaises(ValueError):AdtsReader(f).frame()

    def test_paused_source_keeps_encoder_clock_running(self):
        import shutil,threading
        from carplay_proto.aac import AacCapture
        if not shutil.which('ffmpeg'):self.skipTest('ffmpeg unavailable')
        r,w=os.pipe();source=os.fdopen(r,'rb',buffering=0);stop=threading.Event()
        capture=AacCapture(source,stop,lambda:1.0)
        try:
            os.write(w,bytes(4096))
            frames=[capture.reader.frame(timeout=12) for _ in range(12)]
            self.assertTrue(all(frames))
            self.assertGreater(capture.underrun_frames,0)
            self.assertIsNone(capture.error)
        finally:
            stop.set();capture.close();os.close(w);source.close()

    def test_two_pa_batches_are_kept_without_dropping_samples(self):
        from carplay_proto.aac import trim_pcm_backlog
        samples=bytes(range(256))*375  # 500ms, two 250ms capture batches
        kept,dropped=trim_pcm_backlog(samples)
        self.assertEqual(kept,samples);self.assertEqual(dropped,0)
    def test_backlog_limit_preserves_sample_alignment_and_newest_audio(self):
        from carplay_proto.aac import trim_pcm_backlog,PCM_BACKLOG_BYTES
        data=bytes(range(256))*1000
        kept,dropped=trim_pcm_backlog(data)
        self.assertEqual(len(kept),PCM_BACKLOG_BYTES)
        self.assertEqual(kept,data[dropped*4:])
    def test_250ms_batch_feed_has_no_padding_or_loss(self):
        import shutil,threading,time
        from carplay_proto.aac import AacCapture
        if not shutil.which('ffmpeg'):self.skipTest('ffmpeg unavailable')
        r,w=os.pipe();source=os.fdopen(r,'rb',buffering=0);stop=threading.Event()
        capture=AacCapture(source,stop,lambda:1.0)
        def writer():
            try:
                for _ in range(6):
                    view=memoryview(bytes(48000))
                    while view:
                        n=os.write(w,view);view=view[n:]
                    if stop.wait(.25):break
            except OSError:pass
        t=threading.Thread(target=writer,daemon=True);t.start()
        try:
            for _ in range(40):self.assertTrue(capture.reader.frame(timeout=12))
            self.assertEqual(capture.underrun_frames,0)
            self.assertEqual(capture.dropped_frames,0)
        finally:
            stop.set();capture.close();source.close();t.join(1);os.close(w)
