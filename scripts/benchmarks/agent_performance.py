"""Authenticated HTTP SSE latency, response contracts and Langfuse usage benchmark.

Creates a uniquely named synthetic account, reads its own seeded orders, and never
confirms tickets/refunds. Handoff scenarios can create synthetic local queue rows;
these require separately approved cleanup. Each session has three turns.
The model output is retained for review: string contracts are not human adjudication.
"""
import argparse
import asyncio
import json
import secrets
import time
from collections import defaultdict
from pathlib import Path

import httpx
from app.config import settings
from scripts.benchmarks.common import ROOT, now, sha, summarize, write_report

from app.core.benchmark_state import SCENARIOS_FILE, business_fingerprint


def load_scenarios():
    data=json.loads(SCENARIOS_FILE.read_text())
    rows=data['scenarios']
    if len({row['id'] for row in rows})!=len(rows) or any(len(row['turns'])!=3 for row in rows):
        raise ValueError('Each unique scenario must have three turns')
    return [(row['id'],[t['prompt'] for t in row['turns']],[t['contract'] for t in row['turns']]) for row in rows]


SCENARIOS = load_scenarios()


class BenchmarkBackendUnavailable(RuntimeError):
    """The running server cannot safely support resumable Agent requests."""


async def check_backend(base_url):
    """Read capabilities before creating accounts, runs, or model requests."""
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
            response = await client.get('/openapi.json')
            response.raise_for_status()
            paths = response.json()['paths']
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise BenchmarkBackendUnavailable(
            'Cannot verify the Agent evaluation API. Check the backend URL and that the server is running. '
            'No evaluation was started; existing checkpoints were kept.') from exc
    required = {'/api/benchmark/conversations': 'post',
                '/api/conversations/{cid}/generation': 'get', '/api/chat': 'post'}
    missing = [path for path, method in required.items() if method not in paths.get(path, {})]
    headers = paths.get('/api/chat', {}).get('post', {}).get('parameters', [])
    if not any(p.get('in') == 'header' and p.get('name', '').lower() == 'x-benchmark-request'
               for p in headers):
        missing.append('X-Benchmark-Request support')
    if missing:
        raise BenchmarkBackendUnavailable(
            'The running backend has not loaded the resumable Agent evaluation API: '
            + ', '.join(missing) + '. Restart the backend when no evaluation is running, '
            'then choose Continue for an existing run, or Rerun for a new test. '
            'No model requests were sent; existing checkpoints were kept.')


def contract(answer, requirements):
    """Lexical screening only; every required concept group must be present."""
    import re
    text=answer.casefold()
    def matches(token):
        value=token.casefold()
        # Numbers and short words must not match unrelated substrings (e.g. 30 in 130).
        return bool(re.search(r'(?<!\w)'+re.escape(value)+r'(?!\w)',text)) if value.isalnum() and (len(value)<4 or value.isdigit()) else value in text
    if isinstance(requirements,list):return bool(text.strip()) and any(matches(t) for t in requirements)
    return bool(text.strip()) and all(any(matches(t) for t in group) for group in requirements['all_of_any']) and not any(matches(t) for t in requirements.get('none_of',[]))


async def consume_sse(response,started,clock=time.perf_counter):
    result={'answer':'','ttft_ms':None,'terminal':None,'tools':[],'actions':[],
            'error':None,'conversation_id':None,'http_status':response.status_code}
    event='message';terminal_ms=None
    async for line in response.aiter_lines():
        if line.startswith('event:'):event=line[6:].strip()
        if not line.startswith('data:'):continue
        payload=line[5:].strip()
        if payload=='[DONE]':
            continue  # End marker is not JSON; still drain until transport EOF.
        value=json.loads(payload)
        if event=='error':result['error']='sse_error';break
        if value.get('conversation_id'):result['conversation_id']=value['conversation_id']
        if value.get('delta'):
            if result['ttft_ms'] is None:result['ttft_ms']=1000*(clock()-started)
            result['answer']+=value['delta']
        kind=value.get('event')
        if kind=='tool':result['tools'].append(value.get('name'))
        if kind=='actions':result['actions'].extend(value.get('items',[]))
        if kind in ('done','interrupt') and terminal_ms is None:
            terminal_ms=1000*(clock()-started);result['terminal']=kind
            # Drain to EOF: the producer must commit final state before next turn.
    result['stream_closed_ms']=1000*(clock()-started)
    result['latency_ms']=terminal_ms if terminal_ms is not None else result['stream_closed_ms']
    if not result['terminal'] and not result['error']:result['error']='missing_terminal_event'
    return result


def price_observations(observations, pricing):
    seen=set();calls=[];unknown=[];measured=[];missing_tokens=[]
    for obs in observations:
        oid=obs['id']
        if oid in seen or obs.get('type') not in ('GENERATION','EMBEDDING'):continue
        seen.add(oid)
        model=obs.get('model');usage=obs.get('usage') or {};rate=pricing['models'].get(model)
        inp=usage.get('input');out=usage.get('output')
        # Legacy usage.output already includes reasoning; do not add output_reasoning twice.
        metadata=obs.get('metadata') or {}
        missing=metadata.get('usage_missing') or str(metadata.get('usage_source','')).startswith('estimated') or inp is None or out is None
        if missing:
            missing_tokens.append(oid)
        else:
            measured.append((inp, out))
        if missing or not rate or (rate.get('max_input_tokens') and inp>rate['max_input_tokens']):
            unknown.append({'id':oid,'model':model,'reason':'missing_usage_or_price_or_unsupported_tier'});continue
        value=(inp*rate['input_per_million']+out*rate['output_per_million'])/1_000_000
        calls.append({'id':oid,'model':model,'input_tokens':inp,'output_tokens':out,'estimated_cny':value})
    return {'calls':calls,'unknown':unknown,'estimated_cny':sum(x['estimated_cny'] for x in calls),
            'complete':bool(calls) and not unknown,'input_tokens':sum(x['input_tokens'] for x in calls),
            'output_tokens':sum(x['output_tokens'] for x in calls),
            'token_complete':bool(measured) and not missing_tokens,
            'provider_input_tokens':sum(x[0] for x in measured),
            'provider_output_tokens':sum(x[1] for x in measured)}


async def collect_usage(cids,pricing):
    results={}
    from app.usage_store import session_usage
    remaining=[]
    for cid in cids:
        local=session_usage(cid)
        if local is None:
            remaining.append(cid)
            continue
        observations=[{'id':c['id'], 'model':c['model'], 'type':'GENERATION',
                       'usage':{'input':c['input'], 'output':c['output']},
                       'metadata':{'usage_missing':c['source']!='provider', 'usage_source':c['source']}}
                      for c in local['calls']]
        results[str(cid)]={**price_observations(observations,pricing), 'source':'local_backend',
                           'trace_ids':[t['id'] for t in local['turns'] if t['status']=='completed']}
    cids=remaining
    if not cids:
        return results
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return results | {str(cid):{'complete':False,'reason':'usage_not_recorded'} for cid in cids}
    auth=(settings.langfuse_public_key,settings.langfuse_secret_key)
    async with httpx.AsyncClient(base_url=settings.langfuse_base_url.rstrip('/'),auth=auth,timeout=30) as client:
        for cid in cids:
            observations=[];trace_ids=[];page=1
            while True:
                r=await client.get('/api/public/traces',params={'sessionId':str(cid),'limit':100,'page':page});r.raise_for_status()
                data=r.json();traces=data.get('data',[])
                for trace in traces:
                    rr=await client.get('/api/public/traces/'+trace['id']);rr.raise_for_status()
                    observations.extend(rr.json().get('observations',[]));trace_ids.append(trace['id'])
                if page>=(data.get('meta',{}).get('totalPages') or 1):break
                page+=1
            results[str(cid)]={**price_observations(observations,pricing),'trace_ids':trace_ids}
    return results


def finalize_report(report):
    """Summarize observed turns, retaining early stops and unknown usage."""
    turns=[t for s in report['sessions'] for t in s['turns']]
    normal=[t for t in turns if not t['error'] and t['terminal']=='done']
    sessions=report['sessions']
    priced=[report['usage'][str(s['conversation_id'])] for s in sessions
            if len(s['turns'])==3 and all(not t['error'] and t['terminal']=='done' for t in s['turns'])
            and report['usage'].get(str(s['conversation_id']),{}).get('complete')]
    token_usage=[report['usage'][str(s['conversation_id'])] for s in sessions
                 if len(s['turns'])==3 and all(t['terminal']=='done' and not t['error'] for t in s['turns'])
                 and report['usage'].get(str(s['conversation_id']),{}).get('token_complete',
                     report['usage'].get(str(s['conversation_id']),{}).get('complete', False))]
    report['meta']['token_scope']='Provider-reported input and output tokens summed across model calls in complete three-turn conversations with complete usage traces. Estimated or missing usage is excluded; no price table is required.'
    report['meta']['cost_scope']='Provider-token list-price estimate for completed 3-turn sessions with complete traces; excludes unreported failed attempts, infrastructure and human escalation.'
    report['status']='completed' if len(turns)==report['meta']['n_scenarios']*3*report['meta']['repeats'] else 'incomplete'
    report['meta']['fail_fast_after_consecutive_errors']=6
    report['summary']={'attempted_sessions':len(sessions),'attempted_turns':len(turns),'planned_turns':report['meta']['n_scenarios']*3*report['meta']['repeats'],
        'error_rate':sum(bool(t['error']) for t in turns)/max(len(turns),1),
        'normal_completion_rate':len(normal)/max(len(turns),1),
        'contract_pass_rate':sum(t['contract_pass'] for t in turns)/(report['meta']['n_scenarios']*3*report['meta']['repeats']),
        'successful_turn_latency_ms':summarize([t['latency_ms'] for t in normal]),
        'all_attempt_latency_ms':summarize([t['latency_ms'] for t in turns]),
        'ttft_ms':summarize([t['ttft_ms'] for t in normal]),
        'usage_complete_sessions':len(priced),'session_cost_cny':summarize([v['estimated_cny'] for v in priced]),
        'token_complete_sessions':len(token_usage),
        'session_input_tokens':summarize([v.get('provider_input_tokens',v.get('input_tokens')) for v in token_usage]),
        'session_output_tokens':summarize([v.get('provider_output_tokens',v.get('output_tokens')) for v in token_usage])}
    report['by_scenario']={}
    for name in dict.fromkeys(s['scenario'] for s in sessions):
        selected=[t for s in sessions if s['scenario']==name for t in s['turns']]
        report['by_scenario'][name]={'n':len(selected),'latency_ms':summarize([t['latency_ms'] for t in selected]),
            'contract_pass':sum(t['contract_pass'] for t in selected)}
    return report


async def main(args):
    if not getattr(args, 'preflight_checked', False):
        await check_backend(args.base_url)
    scenarios=[s for s in SCENARIOS if not args.scenario or s[0] in args.scenario]
    from scripts.eval_rag import _load
    from app.kb.evaluation import check_live_annotations
    await check_live_annotations(_load())
    pricing=json.loads((ROOT/'data/benchmarks/pricing.json').read_text())
    from app.agent_resume import signature, prepare
    credentials=ROOT/'data/benchmarks'/(args.output+'.credentials.json')
    resuming=getattr(args, 'resume', False)
    if resuming:
        report=json.loads((ROOT/'data/benchmarks'/(args.output+'.json')).read_text())
        if report['meta'].get('resume_signature') != signature():
            raise ValueError('Agent models, configuration, business, or code changed. Rerun is required.')
        if (report['meta'].get('selected_scenarios') != [x[0] for x in scenarios]
                or report['meta']['repeats'] != args.repeats or report['meta']['concurrency'] != args.concurrency):
            raise ValueError('Agent scenario selection, repeat count, or concurrency changed. Rerun is required.')
        saved=json.loads(credentials.read_text())
        uid,password=saved['username'],saved['password']
    else:
        uid='bench_'+secrets.token_hex(6);password=secrets.token_urlsafe(24)
        report={'status':'running','meta':{'started_at':now(),'base_url':args.base_url,'repeats':args.repeats,'concurrency':args.concurrency,
            'n_scenarios':len(scenarios),'language':'en-US','scenario_version':json.loads(SCENARIOS_FILE.read_text())['version'],
            'business_fingerprint':business_fingerprint(),'scenarios_sha256':sha(SCENARIOS_FILE),'account':uid,'model':settings.chat_model,'pricing':pricing,
            'pricing_sha256':sha(ROOT/'data/benchmarks/pricing.json'),
            'latency_scope':'Actual authenticated HTTP SSE from request to first nonempty answer delta and final done/interrupt event. Stream is drained to EOF before next turn; stream_closed_ms is separate. Excludes login and human wait time.',
            'quality_scope':'Heuristic response contracts, not human-rated task resolution.',
            'workload':f'{len(scenarios)} synthetic scenarios, 3 turns each, balanced by scenario; not production traffic.'},'sessions':[]}
        from app.agent_resume import signature
        report['meta']['resume_signature']=signature()
        report['meta']['selected_scenarios']=[x[0] for x in scenarios]
        write_report(args.output,report)
        import os
        fd=os.open(credentials, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump({'username':uid,'password':password},stream)
    sem=asyncio.Semaphore(args.concurrency)
    stop=asyncio.Event()
    consecutive_errors=0
    async with httpx.AsyncClient(base_url=args.base_url,timeout=180) as client:
        for endpoint in (('login',) if resuming else ('register','login')):
            r=await client.post('/api/auth/'+endpoint,json={'username':uid,'password':password});r.raise_for_status()
        async def run_session(scenario,repeat):
            nonlocal consecutive_errors
            async with sem:
                if stop.is_set():return
                name,texts,checks=scenario
                session=next((x for x in report['sessions'] if x['scenario']==name and x['repeat']==repeat),None)
                if session is None:
                    session={'scenario':name,'repeat':repeat,'turns':[],'conversation_id':None}
                    report['sessions'].append(session)
                if resuming and session.get('pending') and session.get('conversation_id'):
                    snap=await client.get(f"/api/conversations/{session['conversation_id']}/generation")
                    snap.raise_for_status()
                    state=snap.json()
                    if state.get('run_id')==session['pending']['request_id'] and state.get('state')=='failed':
                        session['turns'].append({'turn':session['pending']['turn'], 'error':'previous_generation_failed', 'terminal':None})
                decision=prepare(session)
                if decision in ('reused','blocked'):
                    print(f'Agent {name} repeat={repeat}: {decision}; no model calls.',flush=True)
                    return
                if decision=='restart_failed_conversation':
                    print(f'Agent {name} repeat={repeat}: restarting this failed conversation; other completed conversations are reused.',flush=True)
                cid=session.get('conversation_id')
                if cid is None:
                    created=await client.post('/api/benchmark/conversations')
                    created.raise_for_status()
                    cid=created.json()['conversation_id'];session['conversation_id']=cid
                    write_report(args.output,report)
                first_turn=len(session['turns'])+1
                for turn,(message,check) in enumerate(zip(texts,checks),1):
                    if turn < first_turn:continue
                    payload={'message':message.format(uid=uid)}
                    if cid:payload['conversation_id']=cid
                    pending=session.get('pending')
                    recovering=pending is not None
                    if pending is None:
                        pending={'turn':turn,'request_id':secrets.token_hex(16)}
                        session['pending']=pending
                        write_report(args.output,report)
                    t=time.perf_counter()
                    try:
                        async with client.stream('POST','/api/chat',json=payload,
                            headers={'X-Benchmark-Request':pending['request_id']}) as response:
                            response.raise_for_status()
                            observed=await consume_sse(response,t)
                    except Exception as exc:
                        elapsed=1000*(time.perf_counter()-t)
                        observed={'answer':'','ttft_ms':None,'latency_ms':elapsed,'stream_closed_ms':elapsed,
                            'terminal':None,'tools':[],'actions':[],'error':type(exc).__name__,
                            'http_status':getattr(getattr(exc,'response',None),'status_code',None)}
                    if observed.get('conversation_id'):cid=observed['conversation_id']
                    session['conversation_id']=cid
                    error=observed['error'];terminal=observed['terminal'];elapsed=observed['latency_ms']
                    # Network failures keep the request ID: Continue replays that producer.
                    if observed['error'] in ('ReadTimeout','ReadError','ConnectError','RemoteProtocolError'):
                        write_report(args.output,report)
                        break
                    session.pop('pending',None)
                    if recovering:
                        observed.update(recovered=True, latency_ms=None, ttft_ms=None, stream_closed_ms=None)
                    session['turns'].append({'turn':turn,'prompt':payload['message'],**observed,
                        'contract_pass':not error and terminal=='done' and contract(observed['answer'],check)})
                    write_report(args.output,report)
                    print(f"Agent {name} repeat={repeat} turn={turn}: {'recovered (timing excluded)' if recovering else f'{elapsed/1000:.2f}s'} status={error or terminal}",flush=True)
                    consecutive_errors=consecutive_errors+1 if error else 0
                    if consecutive_errors>=6:stop.set()
                    if error or terminal=='interrupt':break
                session['conversation_id']=cid;write_report(args.output,report)
                print(f"Agent sessions {len(report['sessions'])}/{len(scenarios)*args.repeats}",flush=True)
        await asyncio.gather(*(run_session(scenario,repeat) for repeat in range(args.repeats) for scenario in scenarios))
    # Telemetry delivery is asynchronous. Wait only once, then mark missing data explicitly.
    await asyncio.sleep(8)
    cids=[s['conversation_id'] for s in report['sessions'] if s['conversation_id']]
    try:report['usage']=await collect_usage(cids,pricing)
    except Exception as exc:report['usage_error']=type(exc).__name__;report['usage']={}
    for session in report['sessions']:
        usage=report['usage'].get(str(session['conversation_id']))
        if usage and len(usage.get('trace_ids',[])) < len(session['turns']):
            usage['complete']=False
            usage['token_complete']=False
            usage['reason']='missing_turn_traces'
    finalize_report(report)
    print(write_report(args.output,report),flush=True);print(report['summary'],flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--base-url',default='http://127.0.0.1:8000')
    ap.add_argument('--repeats',type=int,default=3);ap.add_argument('--concurrency',type=int,default=6)
    ap.add_argument('--scenario',action='append',choices=[s[0] for s in SCENARIOS])
    ap.add_argument('--output',default='agent_performance');args=ap.parse_args()
    if args.repeats<1 or args.concurrency<1:ap.error('positive repeats/concurrency required')
    asyncio.run(main(args))
