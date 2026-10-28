"""Stable, non-secret identity of the business/configuration used by Agent evals."""
import hashlib
import json
from app.paths import REPO_ROOT, KNOWLEDGE_DIR, RAG_EVAL_FILE
from app.config import settings

SCENARIOS_FILE = REPO_ROOT/'data/benchmarks/agent_scenarios.json'


def business_fingerprint():
    paths=[*KNOWLEDGE_DIR.glob('*.md'),RAG_EVAL_FILE,RAG_EVAL_FILE.with_name('chunks.json'),
           SCENARIOS_FILE,REPO_ROOT/'data/benchmarks/pricing.json',REPO_ROOT/'app/demo_catalog.py',REPO_ROOT/'app/business_store.py']
    content={str(p.relative_to(REPO_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    content['models']=[settings.chat_model,settings.embed_model,settings.rerank_model]
    return hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest()
