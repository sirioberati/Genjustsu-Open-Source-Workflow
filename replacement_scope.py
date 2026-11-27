"""Temporal replacement scope, enforced locally as well as in the prompt."""
from pathlib import Path
from fractions import Fraction
import json, math
import av


def start_time(folder):
    path=Path(folder)/'replacement-scope.json'
    return json.loads(path.read_text())['start_seconds'] if path.exists() else 0.0


def configure(folder, seconds):
    seconds=float(seconds)
    if not math.isfinite(seconds) or seconds<0:raise ValueError('Replacement start must be a finite, nonnegative number of seconds.')
    source=Path(folder)/'upload.mp4'
    with av.open(str(source)) as c:
        stream=c.streams.video[0]
        duration=float(stream.duration*stream.time_base) if stream.duration else float(c.duration/av.time_base)
    if seconds>=duration:raise ValueError('Replacement start must be before the end of the source video.')
    (Path(folder)/'replacement-scope.json').write_text(json.dumps({'start_seconds':seconds,'prefix':'original source video','audio':'entire original source soundtrack'},indent=2))
    (Path(folder)/'mask-review.json').unlink(missing_ok=True)


def restore_prefix(generated, folder):
    folder=Path(folder);start=start_time(folder)
    if not start:return generated
    target=folder/'seedance-prefix-restored.mp4'
    with av.open(str(generated)) as inp,av.open(str(folder/'upload.mp4')) as source,av.open(str(target),'w') as out:
        video=inp.streams.video[0];rate=video.average_rate or Fraction(24,1)
        stream=out.add_stream('libx264',rate=rate);stream.width=video.width;stream.height=video.height;stream.pix_fmt='yuv420p';stream.options={'crf':'18'}
        original=iter(source.decode(video=0));current=next(original);origin=float(current.time or 0);following=next(original,None)
        for i,frame in enumerate(inp.decode(video=0)):
            seconds=i/float(rate)
            if seconds<start:
                while following is not None and float(following.time or 0)-origin<=seconds:
                    current=following;following=next(original,None)
                frame=current.reformat(width=video.width,height=video.height,format='rgb24')
            frame=av.VideoFrame.from_ndarray(frame.to_ndarray(format='rgb24'),format='rgb24')
            frame.pts=i;frame.time_base=1/rate
            for packet in stream.encode(frame):out.mux(packet)
        for packet in stream.encode():out.mux(packet)
    (folder/'timeline-composition.json').write_text(json.dumps({'original_prefix_seconds':start,'generated_from_seconds':start,'audio':'unchanged original packets','video':'reencoded at generated output dimensions'},indent=2))
    return target
