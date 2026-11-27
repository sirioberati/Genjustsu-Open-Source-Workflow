"""Isolate vocals before generation and replace generated sound with entire original source audio."""
from pathlib import Path
import os,json,time
import av,numpy as np,requests
RATE=44100

def read_audio(path):
    parts=[];res=av.AudioResampler(format='fltp',layout='stereo',rate=RATE)
    with av.open(str(path)) as c:
        if not c.streams.audio:raise ValueError('Source has no audio track.')
        for f in c.decode(audio=0):
            parts.extend(x.to_ndarray() for x in res.resample(f))
        parts.extend(x.to_ndarray() for x in res.resample(None))
    return np.concatenate(parts,axis=1)

def write_audio(path,a):
    with av.open(str(path),'w') as out:
        s=out.add_stream('pcm_s16le',rate=RATE);s.layout='stereo'
        for i in range(0,a.shape[1],4096):
            f=av.AudioFrame.from_ndarray(np.ascontiguousarray(a[:,i:i+4096].astype(np.float32)),format='fltp',layout='stereo');f.sample_rate=RATE;f.pts=i
            for p in s.encode(f):out.mux(p)
        for p in s.encode():out.mux(p)

def separate(src,folder,status=print):
    folder=Path(folder)
    if (folder/'audio-manifest.json').exists():return
    status('Audio · extracting original track');original=read_audio(src);write_audio(folder/'original-audio.wav',original)
    token=os.getenv('REPLICATE_API_TOKEN')
    if not token:raise ValueError('REPLICATE_API_TOKEN is required for audio separation.')
    headers={'Authorization':'Bearer '+token}
    with (folder/'original-audio.wav').open('rb') as f:r=requests.post('https://api.replicate.com/v1/files',headers=headers,files={'content':f},timeout=120)
    r.raise_for_status();url=r.json()['urls']['get'];status('Audio · separating vocals and original music')
    r=requests.post('https://api.replicate.com/v1/predictions',headers=headers,json={'version':'25a173108cff36ef9f80f854c162d01df9e6528be175794b81158fa03836d953','input':{'audio':url,'model_name':'htdemucs','output_format':'wav'}},timeout=60);r.raise_for_status();j=r.json()
    (folder/'audio-prediction.json').write_text(json.dumps(j,indent=2))
    for _ in range(180):
        if j['status'] in ['succeeded','failed','canceled']:break
        time.sleep(5);r=requests.get(j['urls']['get'],headers=headers,timeout=30);r.raise_for_status();j=r.json()
    if j['status']!='succeeded':raise RuntimeError('Audio separation: '+str(j.get('error') or j['status']))
    stems={}
    for name,url in j['output'].items():
        if not url:continue
        r=requests.get(url,timeout=120);r.raise_for_status();p=folder/(name+'.wav');p.write_bytes(r.content);stems[name]=read_audio(p)
    if 'vocals' not in stems or not any(n!='vocals' for n in stems):raise ValueError('Separation returned incomplete stems.')
    music=np.zeros_like(original)
    for name,a in stems.items():
        if name!='vocals':n=min(music.shape[1],a.shape[1]);music[:,:n]+=a[:,:n]
    write_audio(folder/'music.wav',np.clip(music,-1,1))
    (folder/'audio-manifest.json').write_text(json.dumps({'prediction_id':j['id'],'seedance_video':'composite-silent.mp4','seedance_audio':'vocals.wav','final_audio':'upload.mp4 (entire original audio track)','discard_seedance_audio':True,'separation':'Demucs htdemucs; residual music or vocal bleed is possible'},indent=2))

def finish_preview(generated,folder):
    folder=Path(folder);target=folder/'final-preview.mp4'
    # Accommodate a small provider rounding gap without cutting source audio.
    with av.open(str(generated)) as probe, av.open(str(folder/'upload.mp4')) as source:
        stream=probe.streams.video[0]
        vd=float(stream.duration*stream.time_base)
        sd=float(source.duration/av.time_base)
    if 0.25 < sd-vd <= 0.5:
        import subprocess
        padded=folder/'seedance-duration-aligned.mp4'
        from fractions import Fraction
        with av.open(str(generated)) as inp,av.open(str(padded),'w') as out:
            video=inp.streams.video[0];rate=video.average_rate or Fraction(24,1)
            stream=out.add_stream('libx264',rate=rate);stream.width=video.width;stream.height=video.height;stream.pix_fmt='yuv420p';stream.options={'crf':'18'}
            frames=list(inp.decode(video=0));count=round(sd*float(rate))
            for i in range(count):
                f=av.VideoFrame.from_ndarray(frames[min(i,len(frames)-1)].to_ndarray(format='rgb24'),format='rgb24');f.pts=i;f.time_base=1/rate
                for packet in stream.encode(f):out.mux(packet)
            for packet in stream.encode():out.mux(packet)
        (folder/'duration-adjustment.json').write_text(json.dumps({'method':'hold final frame','seconds':sd-vd,'original_audio':'unchanged'}))
        generated=padded
    from replacement_scope import restore_prefix
    generated=restore_prefix(generated,folder)
    # Copy original compressed audio packets, preserving the complete source mix.
    with av.open(str(generated)) as inp,av.open(str(folder/'upload.mp4')) as source_audio,av.open(str(target),'w') as out:
        if not source_audio.streams.audio:raise ValueError('Original source has no audio track.')
        video=inp.streams.video[0];audio=source_audio.streams.audio[0]
        vd=float(video.duration*video.time_base) if video.duration else float(inp.duration/av.time_base)
        sd=float(source_audio.duration/av.time_base)
        if abs(vd-sd)>.25:raise ValueError('Generated duration differs from original audio; refusing to trim, loop or stretch it.')
        vs=out.add_stream_from_template(video);astream=out.add_stream_from_template(audio)
        for p in inp.demux(video=0):
            if p.dts is not None:p.stream=vs;out.mux(p)
        for p in source_audio.demux(audio=0):
            if p.dts is not None:p.stream=astream;out.mux(p)
    return target

def prepare_seedance_video(folder, semitones=3):
    """Embed +3-semitone isolated vocals into the colored-depth composite."""
    import subprocess,shutil
    folder=Path(folder);binary=shutil.which('rubberband')
    if not binary:raise RuntimeError('Rubber Band is required for pitch shifting.')
    pitched=folder/f'vocals-plus{semitones}.wav'
    subprocess.run([binary,'--fine','--pitch',str(semitones),'--time','1',str(folder/'vocals.wav'),str(pitched)],check=True,capture_output=True)
    original=read_audio(folder/'vocals.wav');samples=read_audio(pitched)
    n=original.shape[1]
    samples=np.pad(samples,((0,0),(0,max(0,n-samples.shape[1]))))[:,:n]
    write_audio(pitched,samples)
    target=folder/'seedance-input.mp4'
    with av.open(str(folder/'composite-silent.mp4')) as video,av.open(str(target),'w') as out:
        vs=out.add_stream_from_template(video.streams.video[0]);audio=out.add_stream('aac',rate=RATE);audio.layout='stereo';audio.bit_rate=192000
        for packet in video.demux(video=0):
            if packet.dts is not None:packet.stream=vs;out.mux(packet)
        for i in range(0,n,4096):
            f=av.AudioFrame.from_ndarray(np.ascontiguousarray(samples[:,i:i+4096]),format='fltp',layout='stereo');f.sample_rate=RATE;f.pts=i
            for packet in audio.encode(f):out.mux(packet)
        for packet in audio.encode():out.mux(packet)
    manifest=folder/'audio-manifest.json'
    data=json.loads(manifest.read_text()) if manifest.exists() else {}
    data.update(seedance_video='seedance-input.mp4',seedance_audio=None,pitch_semitones=semitones,embedded_vocals=f'vocals-plus{semitones}.wav',final_audio='entire original source audio')
    manifest.write_text(json.dumps(data,indent=2))
    return target
