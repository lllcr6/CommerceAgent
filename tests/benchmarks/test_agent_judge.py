import json

from langchain_core.runnables import RunnableLambda

from scripts.benchmarks import agent_judge as judge


def scenario(name):
    return {'id': name, 'turns': [{'contract': {'all_of_any': [['ok']]}} for _ in range(3)]}


def session(name):
    return {'scenario': name, 'repeat': 0, 'turns': [
        {'turn': i, 'prompt': 'Question', 'answer': 'Answer', 'tools': [],
         'actions': [], 'terminal': 'done', 'error': None} for i in range(1, 4)]}


def verdict(task='pass', grounding='pass', safety='pass'):
    return {k: {'verdict': v, 'reason': 'Evidence-based reason'} for k, v in
            [('task', task), ('grounding', grounding), ('safety', safety)]}


async def test_judge_checkpoints_success_retries_failures_and_excludes_uncertain(tmp_path, monkeypatch):
    from scripts.benchmarks import common
    monkeypatch.setattr(common, 'OUT', tmp_path)
    monkeypatch.setattr(judge, '_documents', lambda: 'Store policy')
    monkeypatch.setattr(judge.llm, 'resolve_slot', lambda slot: ('judge-model', 'https://example.test', 'secret'))
    cases = [scenario(n) for n in ('passed', 'unknown', 'failed_call')]
    report = {'meta': {'n_scenarios': 3, 'repeats': 1}, 'sessions': [session(x['id']) for x in cases]}
    calls = []
    async def fake(prompt):
        body = json.loads(prompt.messages[-1].content.split('Synthetic conversation and diagnostic hints:\n', 1)[1])
        name = body['scenario']; calls.append(name)
        if name == 'failed_call' and calls.count(name) == 1:
            raise TimeoutError()
        return verdict(grounding='uncertain' if name == 'unknown' else 'pass')
    model = RunnableLambda(fake)
    await judge.evaluate(report, 'run', cases, judge=model)
    assert (report['judge']['pass'], report['judge']['uncertain'], report['judge']['failed_calls']) == (1, 1, 1)
    assert report['judge']['pass_rate'] == 1.0
    assert report['sessions'][2]['judge']['status'] == 'error'
    saved = json.loads((tmp_path / 'run.json').read_text())
    assert saved['judge']['judged'] == 2
    await judge.evaluate(report, 'run', cases, judge=model)
    assert calls.count('passed') == calls.count('unknown') == 1
    assert calls.count('failed_call') == 2
    assert report['judge']['failed_calls'] == 0
    assert report['judge']['assessed'] == 2
    report['sessions'][0]['turns'][0]['answer'] = 'Updated answer'
    await judge.evaluate(report, 'run', cases, judge=model)
    assert calls.count('passed') == 2


async def test_judge_does_not_score_missing_or_failed_transcripts(tmp_path, monkeypatch):
    from scripts.benchmarks import common
    monkeypatch.setattr(common, 'OUT', tmp_path)
    monkeypatch.setattr(judge, '_documents', lambda: 'Policy')
    monkeypatch.setattr(judge.llm, 'resolve_slot', lambda slot: ('judge-model', 'https://example.test', 'secret'))
    broken = session('a'); broken['turns'][0]['error'] = 'ReadError'
    report = {'meta': {'n_scenarios': 1, 'repeats': 1}, 'sessions': [broken]}
    await judge.evaluate(report, 'run', [scenario('a')], judge=RunnableLambda(lambda _: verdict()))
    assert report['judge']['not_evaluated'] == 1
    assert report['judge']['pass_rate'] is None
    assert report['judge']['judged'] == 0


def test_publish_agent_exposes_judge_without_credentials(tmp_path, monkeypatch):
    from scripts.benchmarks import common, publish_admin
    monkeypatch.setattr(common, 'OUT', tmp_path)
    monkeypatch.setattr(publish_admin, 'OUT', tmp_path)
    target = tmp_path / 'admin'
    monkeypatch.setattr(publish_admin, 'OBSERVABILITY_REPORTS_DIR', target)
    record = {'meta': {}, 'summary': {}, 'judge': {'judged': 1, 'pass_rate': 1.0, 'cases': []}}
    (tmp_path / 'agent_performance.json').write_text(json.dumps(record))
    publish_admin.publish_agent()
    published = json.loads((target / 'agent_benchmark.json').read_text())
    assert published['judge'] == record['judge']
    assert 'credentials' not in json.dumps(published)
