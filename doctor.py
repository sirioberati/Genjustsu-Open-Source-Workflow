"""Offline checks; never prints credential values or starts paid calls."""
import argparse,importlib,shutil,sys
from config import setting,generation_provider

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--require-keys',action='store_true');parser.add_argument('--mesh',action='store_true');args=parser.parse_args()
    failed=sys.version_info<(3,12)
    print('Python:',sys.version.split()[0], '(3.12+ required)')
    for name in ['av','numpy','PIL','requests','fastapi','uvicorn','multipart','gradio_client','scipy']:
        try:importlib.import_module(name);print(name+': OK')
        except Exception as exc:print(name+': FAILED ('+type(exc).__name__+')');failed=True
    binary=shutil.which('rubberband');print('rubberband:', 'OK' if binary else 'MISSING — see docs/SETUP-AGENT.md');failed=failed or not binary
    if args.mesh:
        from pathlib import Path
        import subprocess
        worker=Path(__file__).resolve().parent/'.venv-face/bin/python'
        ready=worker.exists() and subprocess.run([str(worker),'-c','import mediapipe,av,PIL,numpy'],capture_output=True).returncode==0
        print('Face mesh worker: '+('OK' if ready else 'MISSING — run bash setup-face-mesh.sh'))
        failed=failed or not ready
    missing=[]
    try:provider=generation_provider()
    except ValueError as e:print(e);return 1
    print('Generation provider:',provider)
    for key in [('FAL_KEY' if provider=='fal' else 'ENHANCOR_API_KEY'),'REPLICATE_API_TOKEN']:
        value=setting(key).strip()
        valid=bool(value) and not any(x in value.lower() for x in ['your_key','your_api','replace_me','placeholder'])
        print(key+': '+('configured (not verified remotely)' if valid else 'MISSING'))
        if not valid:missing.append(key)
    if setting('MEDIA_HOST','tmpfiles') not in ['tmpfiles','catbox']:
        print('MEDIA_HOST must be tmpfiles or catbox');failed=True
    if provider=='enhancor' and not setting('ENHANCOR_WEBHOOK_URL'):
        print('WEBHOOK: not running/configured — install cloudflared and launch the app, or set your own HTTPS callback')
        missing.append('ENHANCOR_WEBHOOK_URL')
    if failed:print('DEPENDENCIES NOT READY');return 1
    if missing:
        print('LOCAL UI READY; GENERATION BLOCKED until '+('keys are configured.' if provider=='fal' else 'keys and the required callback are configured.'))
        return 2 if args.require_keys else 0
    print('LOCAL SETUP READY; provider access/balance has not been verified by this offline check.')
    return 0
if __name__=='__main__':sys.exit(main())
