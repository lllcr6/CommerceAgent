"""Resume rules for stateful synthetic Agent sessions."""
import hashlib
import json
from pathlib import Path
from app.config import settings
from app.core.benchmark_state import business_fingerprint
from app.paths import REPO_ROOT


def signature():
    config={k:v for k,v in settings.model_dump().items() if not any(p in k for p in ['key','secret','password','database'])}
    files=[p for folder in ['app/graph','app/core','app/tools'] for p in (REPO_ROOT/folder).rglob('*.py')]
    return hashlib.sha256(json.dumps({'business':business_fingerprint(), 'config':config,
      'sources':{str(p.relative_to(REPO_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}},sort_keys=True).encode()).hexdigest()


def done(session):
    return len(session['turns'])==3 and all(t.get('terminal')=='done' and not t.get('error') for t in session['turns'])


def prepare(session):
    """Keep good turns; failed stateful conversations restart without hiding prior attempts."""
    if done(session):
        return 'reused'
    if any(t.get('terminal')=='interrupt' for t in session['turns']):
        return 'blocked'
    if any(t.get('error') for t in session['turns']):
        session.setdefault('attempts',[]).append({'conversation_id':session.get('conversation_id'), 'turns':session['turns']})
        session['turns']=[]
        session['conversation_id']=None
        session.pop('pending',None)
        return 'restart_failed_conversation'
    return 'continue'
