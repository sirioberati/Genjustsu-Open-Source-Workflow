import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import av
import fal_bridge
import seedance_bridge


class FalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def reply(self, **data):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = data
        return response

    def queue_reply(self):
        return self.reply(request_id='queue-id', status_url='https://queue.fal.run/bytedance/seedance-2.5/requests/queue-id/status', response_url='https://queue.fal.run/bytedance/seedance-2.5/requests/queue-id')

    def prepare(self):
        (self.folder/'audio-manifest.json').write_text('{}')
        (self.folder/'seedance-input.mp4').write_bytes(b'prepared')
        from PIL import Image
        image = self.folder/'identity.png'
        Image.new('RGB', (300, 300)).save(image)
        return image

    def test_edit_uses_exact_prompt_embedded_audio_and_draft(self):
        reference = self.prepare()
        with patch('mask_review.require_approved'), patch('fal_bridge.validate_video', return_value=5), patch('fal_bridge.credential', return_value='fake'), patch('fal_bridge.upload', return_value='https://media.example/input'), patch('fal_bridge.requests.post', return_value=self.queue_reply()) as post:
            self.assertEqual(seedance_bridge.submit(self.folder, 'Exact reviewed prompt', reference, provider='fal'), 'queue-id')
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['prompt'], 'Exact reviewed prompt')
            self.assertEqual(payload['task'], 'editing')
            self.assertTrue(payload['draft'])
            self.assertEqual(payload['audio_urls'], [])
            self.assertNotIn('webhook_url', payload)
            self.assertEqual(seedance_bridge.saved_request_id(self.folder, 'seedance-response.json'), 'queue-id')
            with self.assertRaises(ValueError):seedance_bridge.submit(self.folder, 'Again', reference, provider='fal')
            self.assertEqual(post.call_count, 1)

    def test_review_gate_precedes_all_network_calls(self):
        with patch('mask_review.require_approved', side_effect=ValueError('Review required')), patch('fal_bridge.requests.post') as post:
            with self.assertRaises(ValueError):fal_bridge.submit(self.folder, 'prompt', 'reference.png')
            post.assert_not_called()

    def test_combined_video_duration_rejected_before_upload(self):
        self.prepare()
        with patch('mask_review.require_approved'), patch('fal_bridge.credential', return_value='fake'), patch('fal_bridge.validate_video', side_effect=[25, 10]), patch('fal_bridge.upload') as upload:
            with self.assertRaisesRegex(ValueError, 'total at most'):fal_bridge.submit(self.folder, 'prompt', 'identity.mov')
            upload.assert_not_called()

    def test_ambiguous_submission_is_never_requeued(self):
        with patch('fal_bridge.credential', return_value='fake'), patch('fal_bridge.requests.post', side_effect=TimeoutError) as post:
            with self.assertRaises(TimeoutError):fal_bridge.queue(self.folder, {}, fal_bridge.MODEL, 'seedance-response.json', {'provider':'fal'})
            with self.assertRaises(ValueError):fal_bridge.queue(self.folder, {}, fal_bridge.MODEL, 'seedance-response.json', {'provider':'fal'})
            with self.assertRaises(ValueError):seedance_bridge.submit(self.folder, 'prompt', 'identity.png', provider='enhancor')
            self.assertEqual(post.call_count, 1)

    def collection_files(self):
        (self.folder/'generation.json').write_text(json.dumps({'provider':'fal','is_draft':True}))
        (self.folder/'seedance-response.json').write_text(json.dumps(self.queue_reply().json()))
        (self.folder/'fal-submission-attempt.json').write_text(json.dumps({'started_at':datetime.now(timezone.utc).isoformat()}))

    def test_resume_collects_draft_id_and_restores_audio(self):
        self.collection_files()
        media = Mock(content=b'video')
        with patch('fal_bridge.credential', return_value='fake'), patch('fal_bridge.requests.get', side_effect=[self.reply(status='COMPLETED'), self.reply(video={'url':'https://media.example/result'},draft_id='actual-draft-id'), media]) as get, patch('fal_bridge.finish_preview') as finish:
            seedance_bridge.wait_and_finish(self.folder, 'queue-id')
            self.assertEqual(get.call_args_list[0].args[0], self.queue_reply().json()['status_url'])
            self.assertNotIn('headers', get.call_args.kwargs)
            self.assertEqual(fal_bridge.saved(self.folder)['draft_id'], 'actual-draft-id')
            finish.assert_called_once()
            self.assertEqual((self.folder/'seedance-result.mp4').read_bytes(), b'video')

    def test_completed_queue_failure_never_downloads_video(self):
        self.collection_files()
        failure = Mock(ok=False, status_code=422)
        with patch('fal_bridge.credential', return_value='fake'), patch('fal_bridge.requests.get', side_effect=[self.reply(status='COMPLETED'), failure]), patch('fal_bridge.finish_preview') as finish:
            with self.assertRaisesRegex(ValueError, 'generation failed'):fal_bridge.wait_and_finish(self.folder, 'queue-id')
            finish.assert_not_called()

    def test_hd_uses_actual_draft_id_and_survives_default_provider_change(self):
        for name in ['upload.mp4','final-preview.mp4']:(self.folder/name).write_bytes(b'original')
        metadata = {'provider':'fal','is_draft':True,'request_id':'queue-id','draft_id':'actual-draft-id','draft_expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
        (self.folder/'generation.json').write_text(json.dumps(metadata))
        with patch('fal_bridge.credential', return_value='fake'), patch('fal_bridge.requests.post', return_value=self.queue_reply()) as post:
            seedance_bridge.submit_hd(self.folder)
            self.assertEqual(post.call_args.kwargs['json'], {'draft_id':'actual-draft-id','resolution':'1080p','output_format':'mp4'})
            self.assertTrue(post.call_args.args[0].endswith('/us/draft/complete'))
            self.assertEqual((self.folder/'hd/upload.mp4').read_bytes(), b'original')
            self.assertEqual(seedance_bridge.job_provider(self.folder/'hd'), 'fal')
            with self.assertRaises(ValueError):seedance_bridge.submit_hd(self.folder)
        metadata['draft_expires_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        (self.folder/'generation.json').write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'expired'):seedance_bridge.submit_hd(self.folder)

    def test_queue_urls_cannot_leak_auth_to_other_hosts(self):
        for url in ['http://queue.fal.run/x','https://evil.example/x','https://queue.fal.run.evil.example/x']:
            with self.assertRaises(ValueError):fal_bridge.queue_url(url)

    def test_video_identity_uses_reference_mode_and_source_framing(self):
        reference = self.prepare()
        source = Mock(duration=5*av.time_base)
        source.streams.video = [Mock(width=540, height=960)]
        opened = Mock()
        opened.__enter__ = Mock(return_value=source)
        opened.__exit__ = Mock(return_value=False)
        with patch('mask_review.require_approved'), patch('fal_bridge.validate_video', return_value=5), patch('fal_bridge.av.open', return_value=opened), patch('fal_bridge.credential', return_value='fake'), patch('fal_bridge.upload', return_value='https://media.example/input'), patch('fal_bridge.requests.post', return_value=self.queue_reply()) as post:
            fal_bridge.submit(self.folder, 'Exact video identity prompt', 'identity.mov', reference)
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['task'], 'reference')
            self.assertEqual(payload['aspect_ratio'], '9:16')
            self.assertEqual(payload['duration'], '5')
            self.assertEqual(len(payload['video_urls']), 2)
            self.assertEqual(len(payload['image_urls']), 1)
            self.assertTrue(fal_bridge.saved(self.folder)['video_identity_experimental'])

    def test_provider_aware_doctor_requires_no_enhancor_callback_for_fal(self):
        import doctor
        import sys
        settings = {'FAL_KEY':'fake','REPLICATE_API_TOKEN':'fake','MEDIA_HOST':'tmpfiles'}
        with patch.object(sys, 'argv', ['doctor.py','--require-keys']), patch('doctor.generation_provider', return_value='fal'), patch('doctor.setting', side_effect=lambda key, default='':settings.get(key,default)), patch('doctor.importlib.import_module'), patch('doctor.shutil.which', return_value='/fake/rubberband'):
            self.assertEqual(doctor.main(), 0)
            settings['FAL_KEY']=''
            self.assertEqual(doctor.main(), 2)

    def test_real_video_input_constraints(self):
        import numpy as np
        video = self.folder/'reference.mp4'
        with av.open(str(video), 'w') as out:
            stream = out.add_stream('libx264', rate=24)
            stream.width=320;stream.height=320;stream.pix_fmt='yuv420p'
            for i in range(48):
                frame=av.VideoFrame.from_ndarray(np.zeros((320,320,3),dtype=np.uint8),format='rgb24')
                for packet in stream.encode(frame):out.mux(packet)
            for packet in stream.encode():out.mux(packet)
        self.assertAlmostEqual(fal_bridge.validate_video(video), 2, places=1)
        with self.assertRaisesRegex(ValueError, 'MP4 or MOV'):fal_bridge.validate_video(self.folder/'identity.webm')
