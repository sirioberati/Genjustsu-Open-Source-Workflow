import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch,Mock
import mask_review,seedance_bridge
class FaceMeshTests(unittest.TestCase):
 def test_mesh_approval_tracks_overlay_and_audio_without_masks(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'workflow-mode.json').write_text('{"mode":"face_mesh"}')
   for n in ['original.mp4','face-landmarks.json','composite-silent.mp4','seedance-input.mp4']:(p/n).write_bytes(b'test')
   mask_review.review(p,True,'Full mesh reviewed',mask_review.fingerprint(p));mask_review.require_approved(p)
   (p/'seedance-input.mp4').write_bytes(b'changed')
   with self.assertRaises(ValueError):mask_review.require_approved(p)
 def test_mesh_submission_does_not_rebuild_depth_input(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'workflow-mode.json').write_text('{"mode":"face_mesh"}');(p/'audio-manifest.json').write_text('{}')
   response=Mock();response.json.return_value={'requestId':'mesh-test'}
   with patch('mask_review.require_approved'),patch('seedance_bridge.credential',return_value='test'),patch('seedance_bridge.setting',return_value='https://example.org'),patch('seedance_bridge.upload',return_value='https://example.org/video'),patch('audio_workflow.prepare_seedance_video') as prepare,patch('seedance_bridge.requests.post',return_value=response) as post:
    seedance_bridge.submit(p,'Replace subject','reference.png',provider='enhancor');prepare.assert_not_called()
    payload=post.call_args.kwargs['json'];self.assertIn('Remove all face mesh lines',payload['prompt']);self.assertNotIn('colored-depth',payload['prompt']);self.assertTrue(payload['is_draft'])
