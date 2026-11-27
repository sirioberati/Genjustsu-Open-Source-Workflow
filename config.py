"""Project-local credentials only; environment values take precedence."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def load_env():
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):continue
            key,sep,value=line.partition('=')
            if sep:os.environ.setdefault(key.strip(),value.strip().strip('\"').strip("'"))

def setting(name,default=''):
    load_env()
    value=os.getenv(name,default)
    if name=='ENHANCOR_WEBHOOK_URL' and not value:
        import json
        try:value=json.loads((ROOT/'.runtime-webhook.json').read_text())['url']
        except (OSError,ValueError,KeyError):pass
    return value

def credential(name):
    value=setting(name)
    if not value:raise ValueError(f'Set {name} in this project’s .env file.')
    return value


def generation_provider():
    provider=setting('GENERATION_PROVIDER','enhancor')
    if provider not in ['enhancor','fal']:
        raise ValueError('GENERATION_PROVIDER must be enhancor or fal.')
    return provider
