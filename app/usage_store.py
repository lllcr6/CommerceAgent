"""Local per-call usage, independent of Langfuse. No prompt/answer text is stored."""
import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from langchain_core.callbacks import BaseCallbackHandler
from app.paths import RUNTIME_DIR

PATH = RUNTIME_DIR / 'model_usage.sqlite'
logger = logging.getLogger(__name__)


@contextmanager
def connect():
    PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.executescript('''
    CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, cid TEXT, synthetic INTEGER, intent TEXT DEFAULT 'unknown', status TEXT, created TEXT);
    CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, turn_id TEXT, model TEXT, kind TEXT, input INTEGER, output INTEGER, source TEXT);
    ''')
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def write(sql, args):
    try:
        with connect() as db:
            db.execute(sql, args)
    except Exception:
        logger.warning('Local usage recording unavailable; chat is unaffected', exc_info=True)


class UsageCallback(BaseCallbackHandler):
    run_inline = True

    def __init__(self, cid, user_id=''):
        self.turn_id = uuid.uuid4().hex
        self.started = {}
        self.root = None
        write('INSERT INTO turns(id,cid,synthetic,status,created) VALUES(?,?,?,?,?)',
              (self.turn_id, str(cid), int(str(user_id).startswith('bench_')), 'running', datetime.now(timezone.utc).isoformat()))

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        if parent_run_id is None:
            self.root = run_id

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        if isinstance(outputs, dict) and outputs.get('intent'):
            write('UPDATE turns SET intent=? WHERE id=?', (str(outputs['intent']), self.turn_id))
        if run_id == self.root:
            write('UPDATE turns SET status=? WHERE id=?', ('completed', self.turn_id))

    def on_chain_error(self, error, *, run_id, **kwargs):
        if run_id == self.root:
            write('UPDATE turns SET status=? WHERE id=?', ('failed', self.turn_id))

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        params = kwargs.get('invocation_params') or {}
        model = params.get('model_name') or params.get('model') or (serialized or {}).get('kwargs', {}).get('model_name') or 'unknown'
        chars = sum(len(str(m.content)) for batch in messages for m in batch)
        self.started[str(run_id)] = (model, chars)

    def on_llm_end(self, response, *, run_id, **kwargs):
        model, chars = self.started.pop(str(run_id), ('unknown', 0))
        message = response.generations[0][0].message
        usage = getattr(message, 'usage_metadata', None) or (response.llm_output or {}).get('token_usage') or {}
        inp = usage.get('input_tokens', usage.get('prompt_tokens'))
        out = usage.get('output_tokens', usage.get('completion_tokens'))
        actual = inp is not None and out is not None
        if not actual:
            output_chars = len(str(message.content)) + (len(json.dumps(message.tool_calls)) if message.tool_calls else 0)
            inp, out = (chars + 3)//4, (output_chars+3)//4
        write('INSERT OR REPLACE INTO calls VALUES(?,?,?,?,?,?,?)',
              (str(run_id), self.turn_id, model, 'generation', inp, out, 'provider' if actual else 'estimated_4_chars'))

    def on_llm_error(self, error, *, run_id, **kwargs):
        model, _ = self.started.pop(str(run_id), ('unknown', 0))
        write('INSERT OR REPLACE INTO calls VALUES(?,?,?,?,?,?,?)',
              (str(run_id), self.turn_id, model, 'generation', None, None, 'missing'))


def record_aux(kind, model, tokens, estimated):
    try:
        from langgraph.config import get_config
        turn_id = get_config().get('metadata', {}).get('usage_turn_id')
        if turn_id:
            write('INSERT INTO calls VALUES(?,?,?,?,?,?,?)',
                  (uuid.uuid4().hex, turn_id, model, kind, tokens, 0,
                   'estimated_4_chars' if estimated else ('provider' if tokens is not None else 'missing')))
    except RuntimeError:
        pass  # Offline evaluation has no active chat context.


def session_usage(cid):
    if not PATH.exists():
        return None
    with connect() as db:
        turns = db.execute('SELECT * FROM turns WHERE cid=?', (str(cid),)).fetchall()
        if not turns:
            return None
        rows = db.execute('SELECT c.* FROM calls c JOIN turns t ON c.turn_id=t.id WHERE t.cid=?', (str(cid),)).fetchall()
    return {'turns': [dict(r) for r in turns], 'calls': [dict(r) for r in rows]}


def intent_report(days=7):
    if not PATH.exists():
        return None
    with connect() as db:
        rows = db.execute('''SELECT t.intent, COUNT(DISTINCT t.id) AS count,
            SUM(COALESCE(c.input,0)) AS input_tokens, SUM(COALESCE(c.output,0)) AS output_tokens,
            SUM(CASE WHEN c.source != 'provider' THEN 1 ELSE 0 END) AS estimated_or_missing_calls
            FROM turns t JOIN calls c ON c.turn_id=t.id
            WHERE t.synthetic=0 AND julianday(t.created)>=julianday('now',?) GROUP BY t.intent''', (f'-{days} days',)).fetchall()
    result = [dict(row) for row in rows]
    total = sum(r['input_tokens']+r['output_tokens'] for r in result)
    for r in result:
        r['tokens'] = r['input_tokens']+r['output_tokens']
        r['avg_tokens'] = r['tokens']/r['count']
        r['share'] = r['tokens']/total if total else 0
    result.sort(key=lambda r:r['tokens'], reverse=True)
    return {'meta': {'days':days, 'source':'Local backend usage', 'generated_at':datetime.now(timezone.utc).isoformat()},
            'rows':result, 'total_tokens':total, 'total_requests':sum(r['count'] for r in result)}
