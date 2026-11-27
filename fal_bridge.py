"""fal Seedance drafts. No paid request is retried automatically."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
import json
import shutil
import time

import av
import requests
from config import credential
from media_host import upload
from audio_workflow import finish_preview

MODEL = 'bytedance/seedance-2.5/us/reference-to-video'
COMPLETE = 'bytedance/seedance-2.5/us/draft/complete'


def saved(folder):
    return json.loads((Path(folder)/'generation.json').read_text())


def validate_video(path):
    path = Path(path)
    if path.suffix.lower() not in ['.mp4', '.mov']:
        raise ValueError('fal video references must be MP4 or MOV. Convert WebM explicitly before submission.')
    if path.stat().st_size > 200_000_000:
        raise ValueError('fal video inputs must be at most 200 MB each.')
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        seconds = float(container.duration / av.time_base) if container.duration else float(stream.duration * stream.time_base)
        rate = float(stream.average_rate or 0)
        if not (1.8 <= seconds <= 30.2 and 24 <= rate <= 60
                and 300 <= stream.width <= 6000 and 300 <= stream.height <= 6000
                and .4 <= stream.width / stream.height <= 2.5):
            raise ValueError('fal video requires 1.8–30.2 seconds, 24–60 fps, 300–6000 px per side and aspect ratio 0.4–2.5.')
    return seconds


def queue(folder, payload, model, response_name, metadata):
    folder = Path(folder)
    key = credential('FAL_KEY')
    # Exclusive marker also blocks duplicate requests after ambiguous network failures.
    attempt = folder/'fal-submission-attempt.json'
    try:
        with attempt.open('x') as f:
            json.dump({'model': model, 'started_at': datetime.now(timezone.utc).isoformat()}, f)
    except FileExistsError:
        raise ValueError('fal submission already attempted. Resume the saved request or check fal request history before preparing a deliberate new job.')
    (folder/'generation.json').write_text(json.dumps(metadata, indent=2))
    response = requests.post('https://queue.fal.run/'+model,
                             headers={'Authorization': 'Key '+key}, json=payload, timeout=90)
    # Persist every response before validation. Never store request headers or keys.
    try:
        data = response.json()
    except ValueError:
        raise ValueError(f'fal returned HTTP {response.status_code}. Check request history before retrying.') from None
    (folder/response_name).write_text(json.dumps(data, indent=2))
    if not response.ok:
        raise ValueError(f'fal rejected the request (HTTP {response.status_code}). Check account credits, face permissions and request history.')
    ident = data.get('request_id')
    if not ident:
        raise ValueError('fal returned no request ID. Check request history before retrying.')
    metadata.update(request_id=ident)
    (folder/'generation.json').write_text(json.dumps(metadata, indent=2))
    return ident


def submit(folder, prompt, reference, second=None, status=print):
    from mask_review import require_approved
    folder = Path(folder)
    require_approved(folder)
    if (folder/'seedance-response.json').exists() or (folder/'fal-submission-attempt.json').exists():
        raise ValueError('This job already has a submission. Resume it or prepare a deliberate new job.')
    credential('FAL_KEY')
    if not prompt.strip():
        raise ValueError('Review and provide the exact generation prompt first.')
    if not (folder/'audio-manifest.json').exists():
        raise ValueError('Audio separation must complete before submission.')
    prepared = folder/'seedance-input.mp4'
    if not prepared.exists():
        raise ValueError('Prepare and review the video with embedded vocals before submission.')
    videos = [prepared]
    images = []
    video_identity = Path(reference).suffix.lower() in ['.mp4', '.mov', '.webm']
    if video_identity:
        videos.append(Path(reference))
    else:
        images.append(Path(reference))
    if second:
        images.append(Path(second))
    if sum(validate_video(p) for p in videos) > 30.2:
        raise ValueError('fal source and identity videos must total at most 30.2 seconds. Shorten the reference explicitly before submission.')
    from PIL import Image
    for image in images:
        if image.suffix.lower() not in ['.png','.jpg','.jpeg','.webp'] or image.stat().st_size>30_000_000:
            raise ValueError('fal identity images must be PNG, JPEG or WebP, at most 30 MB each.')
        with Image.open(image) as decoded:decoded.verify()
    status('Uploading prepared video and character references for fal')
    video_urls = [upload(p) for p in videos]
    image_urls = [upload(p) for p in images]
    # Multiple videos use reference mode; editing with a second identity video is unverified.
    task = 'reference' if video_identity else 'editing'
    payload = dict(prompt=prompt, task=task, video_urls=video_urls, image_urls=image_urls,
                   audio_urls=[], draft=True, resolution='1080p', duration='auto',
                   aspect_ratio='auto', generate_audio=True, output_format='mp4')
    if video_identity:
        with av.open(str(prepared)) as source:
            seconds = float(source.duration/av.time_base)
            stream = source.streams.video[0]
            ratio = stream.width/stream.height
        ratios = {'16:9':16/9, '9:16':9/16, '1:1':1, '4:3':4/3, '3:4':3/4, '21:9':21/9}
        payload.update(duration=str(max(4, min(30, round(seconds)))), aspect_ratio=min(ratios, key=lambda r:abs(ratios[r]-ratio)))
    (folder/'seedance-request.json').write_text(json.dumps(payload, indent=2))
    metadata = dict(provider='fal', model=MODEL, mode=task, prompt=prompt, is_draft=True,
                    video='seedance-result.mp4', video_identity_experimental=video_identity)
    return queue(folder, payload, MODEL, 'seedance-response.json', metadata)


def queue_url(value):
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.netloc != 'queue.fal.run' or parsed.username:
        raise ValueError('Invalid fal queue URL in saved response.')
    return value


def wait_and_finish(folder, request_id, status=print):
    folder = Path(folder)
    response_name = 'response.json' if folder.name == 'hd' else 'seedance-response.json'
    response = json.loads((folder/response_name).read_text())
    if response.get('request_id') != request_id:
        raise ValueError('Saved fal request ID does not match.')
    headers = {'Authorization': 'Key '+credential('FAL_KEY')}
    status_url = queue_url(response['status_url'])
    result_url = queue_url(response['response_url'])
    for _ in range(360):
        r = requests.get(status_url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        (folder/'provider-status.json').write_text(json.dumps(data, indent=2))
        if data.get('status') == 'COMPLETED':
            r = requests.get(result_url, headers=headers, timeout=30)
            if not r.ok:
                raise ValueError(f'fal generation failed (HTTP {r.status_code}). See fal request history; no automatic retry.')
            result = r.json()
            (folder/'fal-result.json').write_text(json.dumps(result, indent=2))
            url = result.get('video', {}).get('url', '')
            if not url.startswith('https://'):
                raise ValueError('fal returned no HTTPS result video.')
            if saved(folder).get('is_draft'):
                if not result.get('draft_id'):
                    raise ValueError('fal draft ID missing; HD completion unavailable.')
                metadata = saved(folder)
                # Conservative local expiry starts at submission, not collection.
                started = json.loads((folder/'fal-submission-attempt.json').read_text())['started_at']
                metadata.update(draft_id=result['draft_id'], draft_expires_at=(datetime.fromisoformat(started)+timedelta(days=14)).isoformat())
                (folder/'generation.json').write_text(json.dumps(metadata, indent=2))
            media = requests.get(url, timeout=180)
            media.raise_for_status()
            (folder/'seedance-result.mp4').write_bytes(media.content)
            status('Restoring entire original source audio · discarding generated audio')
            finish_preview(folder/'seedance-result.mp4', folder)
            return
        time.sleep(10)
    raise TimeoutError('fal request still pending. Resume the saved request; do not submit again.')


def submit_hd(folder):
    folder = Path(folder)
    metadata = saved(folder)
    if not metadata.get('is_draft') or not metadata.get('draft_id') or not (folder/'final-preview.mp4').exists():
        raise ValueError('A completed fal draft is required for 1080p completion.')
    if datetime.now(timezone.utc) >= datetime.fromisoformat(metadata['draft_expires_at']):
        raise ValueError('fal draft has expired. Completion requires a draft less than 14 days old on the original account.')
    hd = folder/'hd'
    hd.mkdir(exist_ok=True)
    if (hd/'response.json').exists() or (hd/'fal-submission-attempt.json').exists():
        raise ValueError('HD already attempted. Resume or check fal request history.')
    shutil.copy2(folder/'upload.mp4', hd/'upload.mp4')
    payload = dict(draft_id=metadata['draft_id'], resolution='1080p', output_format='mp4')
    (hd/'request.json').write_text(json.dumps(payload, indent=2))
    return queue(hd, payload, COMPLETE, 'response.json', dict(provider='fal', model=COMPLETE, mode='draft_complete', is_draft=False))
