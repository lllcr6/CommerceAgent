import pytest
from scripts.benchmarks.common import summarize, paired_delta
from scripts.benchmarks.rag_ablation import ndcg, choose
from scripts.benchmarks.agent_performance import price_observations


def test_percentiles_and_empty_values():
    assert summarize([])['mean'] is None
    assert summarize([1,2,3,4]) == {'n':4,'mean':2.5,'p50':2.5,'p95':pytest.approx(3.85)}


def test_paired_bootstrap_reports_negative_results_and_points():
    result=paired_delta([.8,.8,.8],[.6,.6,.6])
    assert result['delta']==pytest.approx(-.2)
    assert result['relative_pct']==pytest.approx(-25)
    assert result['paired_bootstrap_95_ci']==pytest.approx([-.2,-.2])


def test_ndcg_does_not_reward_duplicate_ids():
    assert ndcg([{'id':1},{'id':1}],{1,2}) < 1
    assert ndcg([{'id':1},{'id':2}],{1,2}) == 1


def test_subset_is_reproducibly_balanced_not_first_easy_questions():
    rows=[{'id':str(i),'bucket':str(i%4)} for i in range(20)]
    selected=choose(rows,8,42)
    assert selected==choose(rows,8,42)
    assert {b:sum(r['bucket']==b for r in selected) for b in ('0','1','2','3')}==dict.fromkeys(('0','1','2','3'),2)


def test_reasoning_usage_is_not_double_counted_and_zero_langfuse_cost_not_trusted():
    obs={'id':'x','type':'GENERATION','model':'test','usage':{'input':1000,'output':300},
         'usageDetails':{'output':100,'output_reasoning':200},'calculatedTotalCost':0}
    result=price_observations([obs,obs],{'models':{'test':{'input_per_million':2,'output_per_million':8}}})
    assert result['estimated_cny']==pytest.approx(.0044)
    assert result['output_tokens']==300
    assert len(result['calls'])==1


def test_unknown_price_is_not_reported_as_zero_cost():
    result=price_observations([{'id':'x','type':'GENERATION','model':'unknown','usage':{'input':50,'output':1}}],{'models':{}})
    assert result['complete'] is False
    assert result['unknown']


async def test_sse_done_is_timed_but_connection_drains_before_next_turn():
    from scripts.benchmarks.agent_performance import consume_sse
    state={'clock':0,'drained':False}
    class Response:
        status_code=200
        async def aiter_lines(self):
            yield 'data: {"event":"session","conversation_id":12}'
            state['clock']=1
            yield 'data: {"delta":"你好"}'
            state['clock']=2
            yield 'data: {"event":"done","conversation_id":12}'
            yield 'data: [DONE]'
            # Receiving done must not stop iteration before final server cleanup.
            state['clock']=3;state['drained']=True
            yield ': keep-alive'
    result=await consume_sse(Response(),0,clock=lambda:state['clock'])
    assert state['drained'] is True
    assert result['ttft_ms']==1000
    assert result['latency_ms']==2000
    assert result['stream_closed_ms']==3000
    assert result['conversation_id']==12
    assert result['answer']=='你好'


def test_handoff_followup_rejections_are_separate_from_unexpected_failures():
    from scripts.benchmarks.analyze_agent import analyze
    report={'sessions':[{'conversation_id':1,'turns':[
        {'turn':1,'terminal':'done','tools':['request_human'],'error':None},
        {'turn':2,'terminal':None,'error':'HTTPStatusError','http_status':409}]}], 'usage':{}}
    result=analyze(report)
    assert len(result['handoff_followup_409_rejections'])==1
    assert not result['other_errors']
    assert report['sessions'][0]['turns'][1]['error']=='HTTPStatusError'


def test_completed_cohort_replays_whole_context_and_keeps_raw_errors():
    import copy
    from scripts.benchmarks.complete_agent_cohort import complete_cohort
    def turn(n, error=None):
        return {'turn':n,'error':error,'terminal':None if error else 'done',
                'contract_pass':not error,'latency_ms':100,'ttft_ms':50}
    names=('chitchat','orders_status','orders_product')
    meta={'model':'test','pricing_sha256':'same','n_scenarios':3,'repeats':1,'concurrency':6,'account':'initial'}
    original={'meta':meta,'summary':{'attempted_turns':6},'usage':{},'sessions':[
        {'scenario':name,'repeat':2,'conversation_id':i,'turns':[turn(1),turn(2,'sse_error')]} for i,name in enumerate(names)]}
    supplement={'meta':{**meta,'concurrency':3,'account':'supplement'},'summary':{'attempted_turns':9},'usage':{},'sessions':[
        {'scenario':name,'repeat':0,'conversation_id':i+10,'turns':[turn(1),turn(2),turn(3)]} for i,name in enumerate(names)]}
    snapshot=copy.deepcopy(original)
    cohort=complete_cohort(original,supplement)
    assert original==snapshot
    assert cohort['summary']['attempted_turns']==9
    assert cohort['summary']['usage_complete_sessions']==0  # missing telemetry is not free usage
    assert set(cohort['usage'])==set()
    assert cohort['sessions'][0]['conversation_id']==10
    assert cohort['cohort_provenance']['all_executions']['attempted_turns']==15
    supplement['sessions'][0]['turns'][2]['error']='sse_error'
    with pytest.raises(ValueError,match='did not complete'):
        complete_cohort(original,supplement)


def test_report_selection_never_uses_cohort_after_raw_results_change(tmp_path, monkeypatch):
    import json
    from scripts.benchmarks import common
    monkeypatch.setattr(common,'OUT',tmp_path)
    raw=tmp_path/'agent_performance.json';raw.write_text(json.dumps({'run':'initial'}))
    cohort={'run':'cohort','cohort_provenance':{'source_sha256':{raw.name:common.sha(raw)}}}
    (tmp_path/'agent_completed_cohort.json').write_text(json.dumps(cohort))
    assert common.load_agent_report()[0]['run']=='cohort'
    raw.write_text(json.dumps({'run':'new_run'}))
    assert common.load_agent_report()[0]['run']=='new_run'


def test_admin_export_preserves_metrics_without_inventing_generation_scores():
    from scripts.benchmarks.publish_admin import adapt_rag
    report={'meta':{'n_questions':2,'repeats':2,'metric_k':5,'created_at':'2026-10-21'},
            'summary':{'error_rate':0,'strategies':{'dense':{m:{'mean':.75} for m in ('recall','precision','mrr','ndcg')}}},
            'rows':[{'id':qid,'bucket':bucket,'repeat':repeat,'strategies':{'dense':dict.fromkeys(('recall','precision','mrr','ndcg'),value)}}
                    for qid,bucket,value in [('q1','A_policy',1.),('q2','B_model',.5)] for repeat in range(2)]}
    exported=adapt_rag(report,52)
    assert exported['retrieval']['vector']['overall']['mrr']==.75
    assert exported['retrieval']['vector']['B_model']['precision']==.5
    assert exported['generation'] is None
    assert exported['evidence_coverage']=={}
    assert exported['meta']['chat_model'] is None
    assert exported['meta']['kb_chunks']==52
    report['summary']['error_rate']=.1
    with pytest.raises(ValueError):adapt_rag(report,52)


async def test_observability_returns_agent_benchmark_from_published_report(tmp_path,monkeypatch):
    import json
    from app.api import observability
    async def trend():return {'present':False}
    monkeypatch.setattr(observability,'REPORT_DIR',tmp_path)
    monkeypatch.setattr(observability,'_trend_block',trend)
    monkeypatch.setattr(observability,'_cost_block',lambda:{'present':False})
    monkeypatch.setattr(observability,'_calibration_block',lambda:{'present':False})
    assert (await observability.overview())['agent_benchmark'] is None
    payload={'source_report':'example.json','summary':{'attempted_turns':108}}
    (tmp_path/'agent_benchmark.json').write_text(json.dumps(payload))
    result=(await observability.overview())
    assert result['agent_benchmark']=={**payload,'stale':True}
    assert result['agent_job']['name']=='bench-agent'
    payload['meta']={'business_fingerprint':observability.business_fingerprint()}
    (tmp_path/'agent_benchmark.json').write_text(json.dumps(payload))
    assert (await observability.overview())['agent_benchmark']['stale'] is False


def test_english_contract_checks_all_concepts_and_number_boundaries():
    from scripts.benchmarks.agent_performance import contract,SCENARIOS
    requirement={'all_of_any':[['30','thirty'],['delivery']], 'none_of':['seven days']}
    assert contract('30 days after delivery',requirement)
    assert not contract('130 days after delivery',requirement)
    assert not contract('30 days after purchase',requirement)
    assert not contract('30 days after delivery, or seven days',requirement)
    assert len(SCENARIOS)==12
    assert len({s[0] for s in SCENARIOS})==12
    assert all(len(prompts)==len(checks)==3 for _,prompts,checks in SCENARIOS)
    assert not any(__import__('re').search(r'[\u3400-\u9fff]',p) for _,prompts,_ in SCENARIOS for p in prompts)


def test_agent_evaluation_prevents_cli_and_dashboard_overlapping(tmp_path,monkeypatch):
    from scripts.benchmarks import run_agent_evaluation as runner
    monkeypatch.setattr(runner,'RUNTIME_DIR',tmp_path)
    with runner.evaluation_lock():
        with pytest.raises(RuntimeError,match='already running'):
            with runner.evaluation_lock():pass
    with runner.evaluation_lock():pass


async def test_cancelled_agent_attempt_does_not_replace_published_results(tmp_path,monkeypatch):
    import asyncio,json
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from scripts.benchmarks import run_agent_evaluation as runner
    monkeypatch.setattr(runner,'OUT',tmp_path)
    monkeypatch.setattr(runner,'RUNTIME_DIR',tmp_path/'runtime')
    # write_report resolves its own shared output root.
    from scripts.benchmarks import common
    monkeypatch.setattr(common,'OUT',tmp_path)
    prior={'previous_complete_run':True}
    (tmp_path/'agent_performance.json').write_text(json.dumps(prior))
    async def interrupted(args):
        common.write_report(args.output,{'status':'running','meta':{'account':'bench_unit'},'sessions':[]})
        raise asyncio.CancelledError
    monkeypatch.setattr(runner.agent_performance,'main',interrupted)
    monkeypatch.setattr(runner.agent_performance,'check_backend',AsyncMock())
    monkeypatch.setattr(runner,'publish_agent',lambda:pytest.fail('Cancelled attempts must not be published'))
    code=await runner.main(SimpleNamespace(base_url='unused',repeats=3,concurrency=6,scenario=None))
    assert code==130
    assert json.loads((tmp_path/'agent_performance.json').read_text())==prior
    attempts=list((tmp_path/'agent_runs').glob('*/agent_performance.json'))
    assert len(attempts)==1
    assert json.loads(attempts[0].read_text())['status']=='stopped'
    assert not (tmp_path/'runtime/active_agent_evaluation.json').exists()


def test_provider_token_counts_do_not_require_a_model_price():
    result=price_observations([{'id':'x','type':'GENERATION','model':'unknown',
                               'usage':{'input':50,'output':7}}],{'models':{}})
    assert result['complete'] is False
    assert result['token_complete'] is True
    assert result['provider_input_tokens']==50 and result['provider_output_tokens']==7


@pytest.mark.parametrize("metadata", [{"usage_missing":True}, {"usage_source":"estimated_4_chars"}])
def test_estimated_or_missing_usage_is_not_a_complete_token_measurement(metadata):
    result=price_observations([{'id':'x','type':'GENERATION','model':'unknown',
                               'metadata':metadata,'usage':{'input':50,'output':0}}],{'models':{}})
    assert result['token_complete'] is False
    assert result['provider_input_tokens']==0


def test_input_and_output_averages_use_complete_conversations_independent_of_price():
    from scripts.benchmarks.agent_performance import finalize_report
    turn={'error':None,'terminal':'done','contract_pass':True,'latency_ms':100,'ttft_ms':50}
    report={'meta':{'n_scenarios':3,'repeats':1},'sessions':[
        {'scenario':'test','conversation_id':cid,'turns':[dict(turn) for _ in range(3)]} for cid in (1,2,3)],
        'usage':{'1':{'complete':False,'token_complete':True,'provider_input_tokens':100,'provider_output_tokens':20},
                 '2':{'complete':False,'token_complete':True,'provider_input_tokens':300,'provider_output_tokens':40},
                 '3':{'complete':False,'token_complete':False,'provider_input_tokens':999,'provider_output_tokens':999}}}
    summary=finalize_report(report)['summary']
    assert summary['token_complete_sessions']==2
    assert summary['usage_complete_sessions']==0
    assert summary['session_input_tokens']['mean']==200
    assert summary['session_output_tokens']['mean']==30
