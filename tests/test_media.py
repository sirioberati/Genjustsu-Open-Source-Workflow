import unittest,tempfile
from pathlib import Path
import av,numpy as np
from fractions import Fraction
from audio_workflow import finish_preview
from pipeline import writer,put,finish,composite

class MediaTests(unittest.TestCase):
 def test_final_audio_packets_equal_source(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)
   with av.open(str(p/'upload.mp4'),'w') as out:
    v=out.add_stream('libx264',rate=24);v.width=64;v.height=64;v.pix_fmt='yuv420p'
    a=out.add_stream('aac',rate=44100);a.layout='stereo'
    for i in range(24):
     f=av.VideoFrame.from_ndarray(np.full((64,64,3),40,dtype=np.uint8),format='rgb24');f.pts=i;f.time_base=Fraction(1,24)
     for packet in v.encode(f):out.mux(packet)
    for packet in v.encode():out.mux(packet)
    samples=np.tile((np.sin(np.arange(44100)*2*np.pi*440/44100)*.1).astype(np.float32),(2,1))
    for i in range(0,44100,4096):
     f=av.AudioFrame.from_ndarray(np.ascontiguousarray(samples[:,i:i+4096]),format='fltp',layout='stereo');f.sample_rate=44100;f.pts=i
     for packet in a.encode(f):out.mux(packet)
    for packet in a.encode():out.mux(packet)
   c,s=writer(p/'generated.mp4',64,64)
   for i in range(24):put(c,s,np.full((64,64,3),150,dtype=np.uint8),i)
   finish(c,s)
   from replacement_scope import configure
   configure(p,.5)
   result=finish_preview(p/'generated.mp4',p)
   def packets(path):
    with av.open(str(path)) as c:return [bytes(x) for x in c.demux(audio=0) if x.dts is not None]
   self.assertEqual(packets(p/'upload.mp4'),packets(result))
   with av.open(str(result)) as c:
    visual=[f.to_ndarray(format='rgb24').mean() for f in c.decode(video=0)]
   self.assertEqual(len(visual),24);self.assertLess(visual[11],60);self.assertGreater(visual[12],130)
 def test_missing_raw_frame_refused(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);(p/'masks').mkdir()
   for name in ['original','depth']:
    c,s=writer(p/(name+'.mp4'),64,64)
    for i in range(2):put(c,s,np.zeros((64,64,3),dtype=np.uint8),i)
    finish(c,s)
   with self.assertRaisesRegex(ValueError,'Frame alignment'):composite(p/'original.mp4',p/'depth.mp4',p/'masks',p)

 def test_missing_mask_at_white_flash_preserves_frame_indices(self):
  from PIL import Image
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);masks=p/'masks';masks.mkdir()
   for name in ['original','depth']:
    c,s=writer(p/(name+'.mp4'),64,64)
    for i in range(3):
     a=np.full((64,64,3),70,dtype=np.uint8)
     if i==1:a[:]=0;a[16:48]=250
     put(c,s,a,i)
    finish(c,s)
   for i in [0,2]:Image.fromarray(np.full((64,64),255,dtype=np.uint8)).save(masks/f'mask_{i:05d}.png')
   self.assertEqual(composite(p/'original.mp4',p/'depth.mp4',masks,p),3)
   from pipeline import frames
   exported=list(frames(p/'composite-silent.mp4'))
   self.assertEqual(len(exported),3)
   self.assertGreater(exported[1][32,32,0],240)
   self.assertTrue((p/'mask-alignment-repair.json').exists())

 def test_missing_mask_on_visible_content_still_refused(self):
  from PIL import Image
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);masks=p/'masks';masks.mkdir()
   for name in ['original','depth']:
    c,s=writer(p/(name+'.mp4'),64,64)
    for i in range(2):put(c,s,np.full((64,64,3),80,dtype=np.uint8),i)
    finish(c,s)
   Image.fromarray(np.full((64,64),255,dtype=np.uint8)).save(masks/'mask_00000.png')
   with self.assertRaisesRegex(ValueError,'Frame alignment'):composite(p/'original.mp4',p/'depth.mp4',masks,p)
   self.assertFalse((p/'composite-silent.mp4').exists())
