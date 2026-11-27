"""Agent CLI. Run from the project directory; all job IDs are local IDs."""
import argparse,json
from pathlib import Path
from config import ROOT,load_env
load_env()
p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
c=sub.add_parser('prepare');c.add_argument('video');c.add_argument('--subject',default='person');c.add_argument('--provider',default='replicate',choices=['replicate','replicate-chenxwh','huggingface'])
for command in ['status','repair-rgb','resume','hd','review','submit']:
 c=sub.add_parser(command);c.add_argument('job')
 if command=='review':c.add_argument('--approve',action='store_true');c.add_argument('--fingerprint',required=True);c.add_argument('--note',required=True)
 if command=='submit':c.add_argument('--prompt-file',required=True);c.add_argument('--reference',required=True);c.add_argument('--second-reference')
 if command=='resume':c.add_argument('--hd',action='store_true')
sub.choices['prepare'].add_argument('--mode',choices=['depth','face_mesh','depth_mesh'],default='depth')
sub.choices['prepare'].add_argument('--replacement-start',type=float,default=0)
a=p.parse_args()
if a.command=='prepare':
 import uuid,shutil
 from pipeline import run
 folder=ROOT/'runs'/uuid.uuid4().hex;folder.mkdir(parents=True)
 shutil.copy2(a.video,folder/'upload.mp4');print('JOB:',folder.name,flush=True)
 from replacement_scope import configure
 configure(folder,a.replacement_start)
 if a.mode=='face_mesh':
  from face_mesh import run as run_mesh
  run_mesh(folder/'upload.mp4',folder)
 elif a.mode=='depth_mesh':
  from face_mesh import run_depth
  run_depth(folder/'upload.mp4',folder,a.subject,a.provider)
 else:run(folder/'upload.mp4',folder,a.subject,a.provider)
 (folder/'status.json').write_text(json.dumps({'id':folder.name,'state':'done','status':'Mask review required'}));raise SystemExit
if len(a.job)!=32 or any(c not in '0123456789abcdef' for c in a.job):p.error('Expected a 32-character local job ID')
folder=ROOT/'runs'/a.job
if not folder.is_dir():p.error('Job does not exist')
if a.command=='status':
 from mask_review import state
 print(json.dumps({'mask_review':state(folder),'generation':json.loads((folder/'generation.json').read_text()) if (folder/'generation.json').exists() else None},indent=2))
elif a.command=='review':
 from mask_review import review
 print(review(folder,a.approve,a.note,a.fingerprint))
elif a.command=='repair-rgb':
 from mask_review import is_mesh
 mode=json.loads((folder/'workflow-mode.json').read_text()).get('mode') if (folder/'workflow-mode.json').exists() else 'depth'
 if mode=='face_mesh':p.error('Fast face mesh has no SAM mask. Reprepare facial tracking instead.')
 from raw_masks import segment_chunked,clean_border_fragments
 from pipeline import composite
 from audio_workflow import prepare_seedance_video
 meta=json.loads((folder/'manifest.json').read_text());repair=folder/'rgb-repair';repair.mkdir(exist_ok=True)
 from replacement_scope import start_time
 masks=clean_border_fragments(segment_chunked(folder/'original.mp4',repair/'chunks',meta.get('prompt','person'),start_time(folder)))
 composite(folder/'original.mp4',folder/'depth.mp4',masks,folder,folder/'upload.mp4')
 if mode=='depth_mesh':
  import shutil,subprocess
  shutil.copy2(folder/'composite-silent.mp4',folder/'depth-composite-silent.mp4')
  subprocess.run([str(ROOT/'.venv-face/bin/python'),str(ROOT/'mesh_worker.py'),str(folder),'--depth'],check=True)
 prepare_seedance_video(folder)
 (folder/'mask-review.json').unlink(missing_ok=True)
 meta['mask_method']='SAM 3 on original RGB, preserving depth colors';(folder/'manifest.json').write_text(json.dumps(meta,indent=2))
 print('Repaired. Review the entire clip again; approval cleared.')
else:
 from seedance_bridge import submit,submit_hd,wait_and_finish
 if a.command=='submit':
  request=submit(folder,Path(a.prompt_file).read_text(),a.reference,a.second_reference)
 elif a.command=='hd':
  request=submit_hd(folder);folder=folder/'hd'
 else:
  folder=folder/'hd' if a.hd else folder
  saved=folder/('response.json' if a.hd else 'seedance-response.json')
  request=json.loads(saved.read_text())['requestId']
 wait_and_finish(folder,request)
 (folder/'status.json').write_text(json.dumps({'id':a.job,'state':'done','status':'Final preview ready · original source audio','final_url':f'/runs/{a.job}/'+('hd/' if folder.name=='hd' else '')+'final-preview.mp4'}))
 print(folder/'final-preview.mp4')
