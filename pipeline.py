from pathlib import Path
from fractions import Fraction
import os, shutil, json, time
import av, numpy as np, requests
from PIL import Image
from gradio_client import Client, handle_file

from config import load_env
load_env()

DEPTH='depth-anything/Video-Depth-Anything'
SAM='linoyts/SAM3-Video'

def frames(path):
    with av.open(str(path)) as c:
        for f in c.decode(video=0): yield f.to_ndarray(format='rgb24')

def writer(path,w,h):
    c=av.open(str(path),'w');s=c.add_stream('libx264',rate=24);s.width=w;s.height=h;s.pix_fmt='yuv420p';s.options={'crf':'18','preset':'fast'}
    return c,s

def put(c,s,a,i):
    f=av.VideoFrame.from_ndarray(a,format='rgb24');f.pts=i;f.time_base=Fraction(1,24)
    for p in s.encode(f):c.mux(p)

def finish(c,s):
    for p in s.encode():c.mux(p)
    c.close()

def normalize(src,dst):
    with av.open(str(src)) as inp:
        vs=inp.streams.video[0];rate=float(vs.average_rate or 24)
        dur=float(vs.duration*vs.time_base) if vs.duration else float(inp.duration/av.time_base)
        if dur>30:raise ValueError('Use a clip of 30 seconds or less for this hosted workflow.')
        it=iter(inp.decode(video=0));cur=next(it);start=float(cur.time or 0);nxt=next(it,None)
        scale=min(1,960/max(cur.width,cur.height));w=max(2,int(cur.width*scale)//2*2);h=max(2,int(cur.height*scale)//2*2)
        out,stream=writer(dst,w,h);count=round(dur*24)
        for i in range(count):
            t=i/24+start
            while nxt is not None and float(nxt.time)<=t:cur=nxt;nxt=next(it,None)
            a=np.asarray(cur.to_image().resize((w,h),Image.Resampling.LANCZOS));put(out,stream,a,i)
        finish(out,stream)
    return {'frames':count,'fps':24,'width':w,'height':h,'duration':count/24}

def file_path(x):
    if isinstance(x,str):return x
    if isinstance(x,dict):return file_path(x.get('video') or x.get('path'))
    raise ValueError('Provider did not return a downloadable video.')

def depth_hf(src,dst):
    c=Client(DEPTH,token=os.getenv('HF_TOKEN') or None,verbose=False)
    result=c.predict({'video':handle_file(str(src))},max_len=-1,target_fps=24,max_res=960,grayscale=False,api_name='/infer_video_depth')
    shutil.copy(file_path(result[1]),dst)

def depth_replicate(src,dst,model_name="lucataco/depth-anything-video"):
    token=os.getenv('REPLICATE_API_TOKEN')
    if not token:raise ValueError('Replicate fallback requires REPLICATE_API_TOKEN in the server environment.')
    # Resolve live model schema instead of assuming an input field.
    headers={'Authorization':f'Bearer {token}'}
    r=requests.get('https://api.replicate.com/v1/models/'+model_name,headers=headers,timeout=30);r.raise_for_status();model=r.json();v=model['latest_version'];props=v['openapi_schema']['components']['schemas']['Input']['properties']
    key=next((k for k in props if 'video' in k and props[k].get('format')=='uri'),None)
    if not key:raise ValueError('Unable to identify Replicate video input in schema.')
    with open(src,'rb') as f:r=requests.post('https://api.replicate.com/v1/files',headers=headers,files={'content':f},timeout=120)
    r.raise_for_status();url=r.json()['urls']['get']
    r=requests.post('https://api.replicate.com/v1/predictions',headers=headers,json={'version':v['id'],'input':{key:url}},timeout=60);r.raise_for_status();j=r.json()
    for _ in range(180):
        if j['status'] in ['succeeded','failed','canceled']:break
        time.sleep(5);r=requests.get(j['urls']['get'],headers=headers,timeout=30);r.raise_for_status();j=r.json()
    if j['status']!='succeeded':raise RuntimeError(str(j.get('error') or j['status']))
    output=j['output'];url=output if isinstance(output,str) else output[0] if isinstance(output,list) else next(v for k,v in output.items() if 'depth' in k)
    r=requests.get(url,timeout=120);r.raise_for_status();Path(dst).write_bytes(r.content)

def grayscale(src,dst,inferno=False):
    out=s=None
    for i,a in enumerate(frames(src)):
        if inferno:
            import cv2
            lut=cv2.applyColorMap(np.arange(256,dtype=np.uint8)[:,None],cv2.COLORMAP_INFERNO)[:,0,::-1].astype(np.float32)
            pixels=a.reshape(-1,3).astype(np.float32);indices=[]
            for chunk in np.array_split(pixels,max(1,len(pixels)//4096)):
                dist=((chunk[:,None,:]-lut[None,:,:])**2).sum(axis=2)
                indices.append(dist.argmin(axis=1).astype(np.uint8))
            gray=np.concatenate(indices).reshape(a.shape[:2]);g=np.repeat(gray[:,:,None],3,axis=2)
        else:g=np.asarray(Image.fromarray(a).convert('L').convert('RGB'))
        if out is None:out,s=writer(dst,g.shape[1],g.shape[0])
        put(out,s,g,i)
    if out is None:raise ValueError('Empty depth video')
    finish(out,s)

def align_blank_flash_mask(original, mask_files, directory, counts):
    """Recover one omitted mask only on a visually empty, near-white flash."""
    if counts[0]!=counts[1] or counts[0]-counts[2]!=1:return mask_files
    indices=[int(p.stem.split('_')[-1]) for p in mask_files]
    missing=set(range(counts[0]))-set(indices)
    if len(missing)!=1 or len(set(indices))!=len(indices) or any(i<0 or i>=counts[0] for i in indices):return mask_files
    index=missing.pop()
    frame=next(a for i,a in enumerate(frames(original)) if i==index)
    # Allow black letterboxing. A visible subject or nonuniform transition fails closed.
    active=np.flatnonzero(np.any(frame>24,axis=(1,2)))
    if len(active)<8:return mask_files
    content=frame[active[0]+2:active[-1]-1]
    if not content.size or content.min()<230 or np.mean(content>=240)<.998:return mask_files
    repair=Path(directory)/'empty-flash-masks';repair.mkdir(exist_ok=True)
    target=repair/f'mask_{index:05d}.png'
    with Image.open(mask_files[0]) as reference:Image.new('L',reference.size,0).save(target)
    (Path(directory)/'mask-alignment-repair.json').write_text(json.dumps({
        'method':'empty mask at near-white flash; existing indices preserved',
        'frame':index,'source_frames':counts[0],'sam_masks':counts[2],
        'review_required':True},indent=2))
    # Existing approval cannot survive an artifact repair.
    (Path(directory)/'mask-review.json').unlink(missing_ok=True)
    return sorted(mask_files+[target],key=lambda p:int(p.stem.split('_')[-1]))

def composite(original,depth,seg,directory,audio_source=None):
    from replacement_scope import start_time
    replacement_start=start_time(directory)
    raw=Path(seg).is_dir()
    mask_files=sorted(Path(seg).glob('mask_*.png')) if raw else []
    counts=[sum(1 for _ in frames(p)) for p in [original,depth]]+[len(mask_files) if raw else sum(1 for _ in frames(seg))]
    if raw and len(set(counts))!=1:
        mask_files=align_blank_flash_mask(original,mask_files,directory,counts)
        counts[2]=len(mask_files)
    if len(set(counts))!=1:raise ValueError(f'Frame alignment failed (original/depth/SAM): {counts}. No misaligned export produced.')
    if raw and [int(p.stem.split('_')[-1]) for p in mask_files]!=list(range(counts[0])):raise ValueError('Missing or shifted frame indices in raw masks.')
    outs={};area=0
    for i,(rgb,d,sam) in enumerate(zip(frames(original),frames(depth),(np.asarray(Image.open(p).convert('RGB')) for p in mask_files) if raw else frames(seg))):
        h,w=rgb.shape[:2]
        if raw:
            mask=(sam[:,:,0]>127).astype(np.uint8)*255
        else:
            # Recover SAM's known 50% green overlay against the untouched depth frame.
            base=np.asarray(Image.fromarray(d).resize((sam.shape[1],sam.shape[0]),Image.Resampling.BILINEAR)).astype(np.float32)
            marked=base*0.5+np.array([0,127.5,0],dtype=np.float32)
            observed=sam.astype(np.float32)
            unchanged_error=((observed-base)**2).sum(axis=2)
            marked_error=((observed-marked)**2).sum(axis=2)
            mask=((marked_error+100<unchanged_error)&(observed[:,:,1]-base[:,:,1]>12)).astype(np.uint8)*255
        mask=np.asarray(Image.fromarray(mask).resize((w,h),Image.Resampling.NEAREST))
        if i/24<replacement_start:mask=np.zeros_like(mask)
        area+=np.count_nonzero(mask)
        d=np.asarray(Image.fromarray(d).resize((w,h),Image.Resampling.BILINEAR));alpha=(mask>127)[:,:,None]
        result=np.where(alpha,d,rgb).astype(np.uint8)
        for name,a in [('mask',np.repeat(mask[:,:,None],3,axis=2)),('composite-silent',result)]:
            if name not in outs:outs[name]=writer(directory/(name+'.mp4'),w,h)
            put(*outs[name],a,i)
    for c,s in outs.values():finish(c,s)
    if area==0:raise ValueError('SAM 3 found no subject in the depth video. Try a simple prompt such as person, or provide a mask manually.')
    final=directory/'composite.mp4'
    with av.open(str(directory/'composite-silent.mp4')) as video, av.open(str(audio_source or original)) as aud, av.open(str(final),'w') as output:
        vs=output.add_stream_from_template(video.streams.video[0])
        astream=output.add_stream_from_template(aud.streams.audio[0]) if aud.streams.audio else None
        for packet in video.demux(video=0):
            if packet.dts is not None:packet.stream=vs;output.mux(packet)
        if aud.streams.audio:
            for packet in aud.demux(audio=0):
                if packet.dts is not None:packet.stream=astream;output.mux(packet)
    return counts[0]

def run(src,directory,prompt='person',provider='replicate',status=print):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    from audio_workflow import separate
    separate(src,directory,status)
    status('Preparing video · 24 fps');meta=normalize(src,directory/'original.mp4')
    status('Video Depth Anything · generating depth')
    if provider=='huggingface':depth_hf(directory/'original.mp4',directory/'depth-raw.mp4')
    else:depth_replicate(directory/'original.mp4',directory/'depth-raw.mp4', 'chenxwh/depth-any-video' if provider=='replicate-chenxwh' else 'lucataco/depth-anything-video')
    shutil.copyfile(directory/'depth-raw.mp4',directory/'depth.mp4')
    status('SAM 3 · segmenting the depth subject')
    from raw_masks import segment_chunked,clean_border_fragments
    from replacement_scope import start_time
    raw_dir=clean_border_fragments(segment_chunked(directory/'depth.mp4',directory/'sam-chunks',prompt,start_time(directory),status=status))
    status('Compositing · depth subject over original background')
    composite(directory/'original.mp4',directory/'depth.mp4',raw_dir,directory,src)
    from audio_workflow import prepare_seedance_video
    status('Embedding isolated vocals · +3 semitones')
    prepare_seedance_video(directory)
    meta.update(prompt=prompt,depth_provider=provider,sam_space=SAM,mask_method='SAM 3 raw PNG masks')
    (directory/'manifest.json').write_text(json.dumps(meta,indent=2));status('Complete')
