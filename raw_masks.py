from pathlib import Path
import os,json,time,zipfile,io
import requests

def segment_raw(video,folder,prompt='person'):
    """Resume a saved SAM request; never automatically repeat a paid POST."""
    import hashlib
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    identity={'sha256':hashlib.sha256(Path(video).read_bytes()).hexdigest(),'prompt':prompt}
    metadata=folder/'sam-input.json';request=folder/'sam-raw-request.json';archive=folder/'sam-masks.zip'
    if metadata.exists() and json.loads(metadata.read_text())!=identity:raise ValueError('SAM input changed; use a new repair folder.')
    if request.exists() and not metadata.exists():raise ValueError('Legacy SAM request exists. Inspect it before creating another request.')
    metadata.write_text(json.dumps(identity,indent=2))
    h={'Authorization':'Bearer '+os.environ['REPLICATE_API_TOKEN']}
    if not archive.exists():
        if request.exists():j=json.loads(request.read_text())
        else:
            attempt=folder/'sam-submission-attempt.json'
            try:
                with attempt.open('x') as f:json.dump(identity,f)
            except FileExistsError:raise ValueError('SAM submission outcome uncertain. Check Replicate request history before retrying.')
            with open(video,'rb') as f:r=requests.post('https://api.replicate.com/v1/files',headers=h,files={'content':f},timeout=120)
            r.raise_for_status();url=r.json()['urls']['get']
            payload={'version':'408f82fc20c300aac5d61d2e34ddb34cd0181e810e9f609d250aed14d5f81269','input':{'video':url,'prompt':prompt,'mask_only':True,'return_zip':True}}
            r=requests.post('https://api.replicate.com/v1/predictions',headers=h,json=payload,timeout=60);r.raise_for_status();j=r.json();request.write_text(json.dumps(j,indent=2));print('SAM raw-mask job:',j['id'],flush=True)
        for _ in range(180):
            if j['status'] in ['succeeded','failed','canceled']:break
            time.sleep(5);r=requests.get(j['urls']['get'],headers=h,timeout=30);r.raise_for_status();j=r.json();request.write_text(json.dumps(j,indent=2))
        if j['status']!='succeeded':raise RuntimeError(str(j.get('error') or j['status']))
        r=requests.get(j['output'],timeout=180);r.raise_for_status();archive.write_bytes(r.content)
    out=folder/'raw-masks';out.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            base=Path(name).name
            if base.startswith('mask_') and base.endswith('.png'):(out/base).write_bytes(z.read(name))
    return out


def segment_chunked(video,folder,prompt='person',start_seconds=0,chunk_frames=72,empty_frames=(),status=print):
    """Segment normalized 24 fps RGB/depth video in resumable, bounded chunks."""
    import hashlib,math,shutil
    import numpy as np
    from PIL import Image
    from pipeline import frames,writer,put,finish,align_blank_flash_mask
    if not math.isfinite(start_seconds) or start_seconds<0 or not 1<=chunk_frames<=96:raise ValueError('Invalid SAM chunk settings.')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    identity={'sha256':hashlib.sha256(Path(video).read_bytes()).hexdigest(),'prompt':prompt,'start_seconds':start_seconds,'chunk_frames':chunk_frames,'empty_frames':sorted(empty_frames)}
    manifest=folder/'chunks.json'
    if manifest.exists() and json.loads(manifest.read_text())!=identity:raise ValueError('Chunked SAM input changed. Use a new repair folder.')
    manifest.write_text(json.dumps(identity,indent=2))
    output=folder/'raw-masks';output.mkdir(exist_ok=True)
    pending=[];first=None;total=0;reports=[]
    def process():
        nonlocal pending,first
        if not pending:return
        chunk=folder/f'chunk_{first:05d}';chunk.mkdir(exist_ok=True);source=chunk/'input.mp4'
        if not source.exists():
            c,s=writer(source,pending[0].shape[1],pending[0].shape[0])
            for i,a in enumerate(pending):put(c,s,a,i)
            finish(c,s)
        status(f'SAM · frames {first}–{first+len(pending)-1} · saved chunks reused on restart')
        masks=segment_raw(source,chunk,prompt)
        files=sorted(masks.glob('mask_*.png'))
        repair_manifest=chunk/'mask-repairs.json'
        if repair_manifest.exists():
            repairs=json.loads(repair_manifest.read_text())
            existing={p.name for p in files}
            for entry in repairs:
                path=chunk/'mask-repairs'/entry['file']
                if path.name!=entry['file'] or path.name in existing or not entry.get('method'):raise ValueError('Invalid or conflicting explicit mask repair.')
                files.append(path)
            files.sort(key=lambda p:int(p.stem.split('_')[-1]))
        files=align_blank_flash_mask(source,files,chunk,[len(pending),len(pending),len(files)])
        indices=[int(p.stem.split('_')[-1]) for p in files]
        if indices!=list(range(len(pending))):raise ValueError(f'SAM chunk at frame {first} has missing or shifted masks; review required, no silent padding.')
        for i,path in enumerate(files):shutil.copy2(path,output/f'mask_{first+i:05d}.png')
        reports.append({'first_frame':first,'frames':len(pending),'folder':chunk.name})
        pending=[];first=None
    for i,a in enumerate(frames(video)):
        total=i+1
        if i/24<start_seconds or i in empty_frames:
            process();Image.fromarray(np.zeros(a.shape[:2],dtype=np.uint8)).save(output/f'mask_{i:05d}.png');continue
        if first is None:first=i
        pending.append(a)
        if len(pending)==chunk_frames:process()
    process()
    if total==0 or start_seconds>=total/24:raise ValueError('Replacement start is outside the video.')
    (folder/'chunk-results.json').write_text(json.dumps({'frames':total,'chunks':reports,'explicit_empty_frames':sorted(empty_frames),'review_required':True},indent=2))
    return output


def clean_border_fragments(folder):
    """Remove tiny, narrow disconnected edge fragments; preserve large edge subjects."""
    import numpy as np
    from PIL import Image
    from scipy.ndimage import label
    folder=Path(folder);output=folder.parent/'clean-masks';output.mkdir(exist_ok=True)
    report=[]
    for p in sorted(folder.glob('mask_*.png')):
        a=np.asarray(Image.open(p).convert('L'))>127;labels,_=label(a);h,w=a.shape;removed=0
        for ident in (set(labels[:,0])|set(labels[:,-1]))-{0}:
            y,x=np.where(labels==ident)
            if len(x)<h*w*.03 and x.max()-x.min()+1<=max(6,int(w*.05)):
                a[labels==ident]=False;removed+=len(x)
        Image.fromarray(a.astype(np.uint8)*255).save(output/p.name)
        report.append({'frame':p.stem,'removed_border_pixels':removed,'mask_pixels':int(a.sum()),'left_right_edge_pixels':int(a[:,0].sum()+a[:,-1].sum())})
    (folder.parent/'mask-cleanup-report.json').write_text(json.dumps(report,indent=2))
    return output
