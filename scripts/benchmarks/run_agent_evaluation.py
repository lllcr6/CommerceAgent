"""One admin/CLI job: run current Agent cases, derive costs, publish, then refresh.

Each attempt has a unique directory. Only a finished attempt replaces the latest
report; cancellation/launch failure leaves previous published results intact.
"""
import argparse
import asyncio
import json
import secrets
import shutil
import os
import signal
import sqlite3
from contextlib import contextmanager
from app.paths import RUNTIME_DIR
from app.core.benchmark_state import business_fingerprint
from types import SimpleNamespace
from scripts.benchmarks import agent_performance, analyze_agent, agent_judge
from scripts.benchmarks.common import OUT, now, write_report
from scripts.benchmarks.publish_admin import publish_agent


def promote(report, run_dir):
    # Preserve the previous raw report and the exact inputs of legacy cohorts.
    for name in ('agent_performance.json','agent_completed_cohort.json','agent_quota_supplement.json',
                 'agent_outcomes.json'):
        path=OUT/name
        if path.exists():
            previous=run_dir/'previous';previous.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,previous/name)
    write_report('agent_performance',report)
    outcomes=analyze_agent.analyze(report)
    outcomes['source_report']='agent_performance.json'
    write_report('agent_outcomes',outcomes)
    publish_agent()
    return outcomes


@contextmanager
def evaluation_lock():
    RUNTIME_DIR.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(RUNTIME_DIR/'agent_evaluation_lock.sqlite',timeout=0)
    try:
        connection.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError as error:
        connection.close()
        raise RuntimeError('An Agent evaluation is already running. Wait for it to finish.') from error
    try:yield
    finally:connection.rollback();connection.close()


async def main(args):
    with evaluation_lock():
        try:
            return await run(args)
        except agent_performance.BenchmarkBackendUnavailable as exc:
            print(f'Agent evaluation not started: {exc}', flush=True)
            return 1


async def run(args):
    await agent_performance.check_backend(args.base_url)
    pointer=OUT/'agent_runs'/'current.json'
    resuming=getattr(args,'resume',False)
    if resuming:
        if not pointer.exists():
            raise ValueError('No resumable Agent evaluation exists. Run a new evaluation first.')
        output=json.loads(pointer.read_text())['output']
        path=(OUT/(output+'.json')).resolve()
        if not path.is_relative_to((OUT/'agent_runs').resolve()):
            raise ValueError('Invalid Agent checkpoint path')
        run_id=path.parent.name
    else:
        run_id=now().replace(':','').replace('.','')+'-'+secrets.token_hex(3)
        output='agent_runs/'+run_id+'/agent_performance'
        from app.kb.eval_checkpoint import atomic_json
        atomic_json(pointer,{'output':output})
    run_dir=OUT/'agent_runs'/run_id
    print('Starting Agent evaluation: English business cases, authenticated multi-turn conversations.',flush=True)
    marker=RUNTIME_DIR/'active_agent_evaluation.json'
    marker.write_text(json.dumps({'pid':os.getpid(),'process_group':os.getpgrp(),'report':output+'.json'}))
    try:
        await agent_performance.main(SimpleNamespace(base_url=args.base_url,repeats=args.repeats,
            concurrency=args.concurrency,scenario=args.scenario,output=output,resume=resuming,
            preflight_checked=True))
        report = json.loads((OUT / (output + '.json')).read_text())
        if report['meta']['business_fingerprint'] != business_fingerprint():
            print('Business data or evaluation cases changed during the run; rerun with a stable configuration.', flush=True)
            return 1
        scenarios = json.loads(agent_performance.SCENARIOS_FILE.read_text())['scenarios']
        print('Judging observable conversation quality; unavailable results remain unscored.', flush=True)
        await agent_judge.evaluate(report, output, scenarios, concurrency=args.concurrency)
    except asyncio.CancelledError:
        path=OUT/(output+'.json')
        if path.exists():
            stopped=json.loads(path.read_text())
            stopped['status']='stopped';stopped['meta']['finished_at']=now()
            stopped['stop_reason']='Stopped by the operator. Continue preserves completed conversations and replays pending requests.'
            write_report(output,stopped)
        print('Evaluation stopped. Checkpoints and previous published results were kept. Continue resumes this run.',flush=True)
        return 130
    finally:
        if marker.exists():marker.unlink()

    report=json.loads((OUT/(output+'.json')).read_text())
    report['meta'].update(run_id=run_id,finished_at=now(),run_report=output+'.json')
    write_report(output,report)
    if report['meta']['business_fingerprint']!=business_fingerprint():
        print('Business data or evaluation cases changed during the run. Results were saved separately; rerun with a stable configuration.',flush=True)
        return 1
    # Smoke/subset runs stay separate from the full admin benchmark.
    if args.scenario or args.repeats!=3:
        print('Subset run saved; full benchmark results were not replaced.',flush=True)
        return 0
    outcomes=promote(report,run_dir)
    print('Evaluation results and cost estimates updated. Refresh the dashboard to view them.',flush=True)
    return 1 if outcomes['other_errors'] or (report.get('judge') or {}).get('failed_calls') or len(report['sessions'])!=report['meta']['n_scenarios']*args.repeats else 0


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--base-url',default='http://127.0.0.1:8000')
    ap.add_argument('--repeats',type=int,default=3)
    ap.add_argument('--concurrency',type=int,default=6)
    ap.add_argument('--scenario',action='append',choices=[s[0] for s in agent_performance.SCENARIOS])
    ap.add_argument('--continue',dest='resume',action='store_true')
    args=ap.parse_args()
    if args.repeats<1 or args.concurrency<1:ap.error('positive repeats/concurrency required')
    async def entry():
        loop=asyncio.get_running_loop();task=asyncio.current_task()
        for sig in (signal.SIGTERM,signal.SIGINT):
            loop.add_signal_handler(sig,task.cancel)
        return await main(args)
    raise SystemExit(asyncio.run(entry()))
