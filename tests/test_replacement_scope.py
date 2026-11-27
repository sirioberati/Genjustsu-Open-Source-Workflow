import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import av
import numpy as np
from PIL import Image
from pipeline import writer,put,finish,frames
from replacement_scope import configure,restore_prefix,start_time
from raw_masks import segment_chunked
from mask_review import fingerprint


class ReplacementScopeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
 def video(self,name,count=48,value=40):
  path=self.folder/name;c,s=writer(path,64,64)
  for i in range(count):put(c,s,np.full((64,64,3),value,dtype=np.uint8),i)
  finish(c,s);return path
 def test_original_prefix_is_restored_and_generated_tail_retained(self):
  self.video('upload.mp4',48,40);generated=self.video('generated.mp4',48,170)
  configure(self.folder,1)
  result=restore_prefix(generated,self.folder);decoded=list(frames(result))
  self.assertEqual(len(decoded),48)
  self.assertLess(decoded[23].mean(),60);self.assertGreater(decoded[24].mean(),150)
  self.assertEqual(start_time(self.folder),1)
 def test_invalid_start_rejected(self):
  self.video('upload.mp4')
  for start in [-1,float('nan'),float('inf'),2,3]:
   with self.assertRaises(ValueError):configure(self.folder,start)
 def test_scope_change_invalidates_mask_fingerprint(self):
  from mask_review import FILES
  for name in FILES:(self.folder/name).write_bytes(b'original')
  initial=fingerprint(self.folder)
  (self.folder/'replacement-scope.json').write_text('{"start_seconds":7}')
  self.assertNotEqual(initial,fingerprint(self.folder))
 def test_chunks_preserve_global_indices_and_skip_prefix(self):
  source=self.video('source.mp4',12)
  calls=[]
  def segment(video,folder,prompt):
   count=len(list(frames(video)));calls.append(count)
   masks=Path(folder)/'raw-masks';masks.mkdir(exist_ok=True)
   for i in range(count):Image.new('L',(64,64),255).save(masks/f'mask_{i:05d}.png')
   return masks
  with patch('raw_masks.segment_raw',side_effect=segment):
   result=segment_chunked(source,self.folder/'chunks','main subject',start_seconds=4/24,chunk_frames=3)
  self.assertEqual(calls,[3,3,2])
  masks=sorted(result.glob('mask_*.png'));self.assertEqual(len(masks),12)
  for i,p in enumerate(masks):self.assertEqual(bool(np.asarray(Image.open(p)).any()),i>=4)
 def test_missing_mask_on_visible_chunk_is_not_padded(self):
  source=self.video('source.mp4',3)
  def segment(video,folder,prompt):
   masks=Path(folder)/'raw-masks';masks.mkdir(exist_ok=True)
   for i in [0,2]:Image.new('L',(64,64),255).save(masks/f'mask_{i:05d}.png')
   return masks
  with patch('raw_masks.segment_raw',side_effect=segment):
   with self.assertRaisesRegex(ValueError,'missing or shifted'):segment_chunked(source,self.folder/'chunks',chunk_frames=3)
 def test_saved_sam_request_is_polled_without_resubmission(self):
  import hashlib,zipfile
  from raw_masks import segment_raw
  source=self.video('source.mp4',3);folder=self.folder/'sam';folder.mkdir()
  (folder/'sam-input.json').write_text(json.dumps({'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'prompt':'person'}))
  (folder/'sam-raw-request.json').write_text(json.dumps({'id':'saved','status':'processing','urls':{'get':'https://example.test/status'}}))
  from unittest.mock import Mock
  status=Mock();status.json.return_value={'status':'failed','error':'provider failure'}
  with patch('raw_masks.requests.post') as post,patch('raw_masks.requests.get',return_value=status),patch('raw_masks.time.sleep'),patch.dict('os.environ',{'REPLICATE_API_TOKEN':'fake'}):
   with self.assertRaisesRegex(RuntimeError,'provider failure'):segment_raw(source,folder)
   post.assert_not_called()
 def test_composite_excludes_subject_before_start(self):
  from pipeline import composite
  original=self.video('original.mp4',4,40);depth=self.video('depth.mp4',4,170)
  masks=self.folder/'masks';masks.mkdir()
  for i in range(4):Image.new('L',(64,64),255).save(masks/f'mask_{i:05d}.png')
  (self.folder/'replacement-scope.json').write_text('{"start_seconds":0.08333333333333333}')
  composite(original,depth,masks,self.folder)
  output=list(frames(self.folder/'composite-silent.mp4'));mask=list(frames(self.folder/'mask.mp4'))
  self.assertLess(output[1].mean(),60);self.assertGreater(output[2].mean(),150)
  self.assertLess(mask[1].mean(),10);self.assertGreater(mask[2].mean(),240)
