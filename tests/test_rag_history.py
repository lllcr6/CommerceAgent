import json
from types import SimpleNamespace
from app.rag_history import publish, completed_runs

def report(complete=True):
    return {'meta':{'status':'completed' if complete else 'partial','generated_at':'2026-10-22 01:00',
      'n_samples':2,'relevance_version':'exact-v1','chat_model':'test','judge_model':'judge'},
      'retrieval':{'hybrid_rerank':{'overall':{'recall':1,'precision':0.5,'mrr':0.9}}},
      'generation':{'completion':{'complete':complete},'faithfulness':{'A_policy':{'v':0,'answered':1}},
                    'refusal':{'rate':1}}}

def test_only_complete_runs_enter_trend_and_continue_has_one_point(tmp_path):
    run=SimpleNamespace(run_id='first')
    (tmp_path/'runs/first/checkpoints').mkdir(parents=True)
    publish(tmp_path,run,report(False),'partial')
    assert completed_runs(tmp_path)==[]
    publish(tmp_path,run,report(),'complete')
    assert len(completed_runs(tmp_path))==1
    assert completed_runs(tmp_path)[0]['metrics']['faithfulness']==0
    assert not (tmp_path/'runs/first/attempts').exists()
    assert not (tmp_path/'legacy').exists()
    (tmp_path/'runs/second/checkpoints').mkdir(parents=True)
    publish(tmp_path,SimpleNamespace(run_id='second'),report(),'new')
    assert len(completed_runs(tmp_path))==2
    assert (tmp_path/'runs/first/rag_eval.json').exists()

def test_publish_does_not_archive_latest_view_or_recreate_missing_run(tmp_path):
    import pytest
    (tmp_path/'rag_eval.json').write_text(json.dumps({'meta':{'n_samples':121}}))
    with pytest.raises(ValueError, match='experiment is missing'):
        publish(tmp_path,SimpleNamespace(run_id='new'),report(False),'partial')
    assert not (tmp_path/'runs').exists()
    (tmp_path/'runs/new/checkpoints').mkdir(parents=True)
    publish(tmp_path,SimpleNamespace(run_id='new'),report(False),'partial')
    assert not (tmp_path/'legacy').exists()
    assert not (tmp_path/'runs/new/attempts').exists()
    assert completed_runs(tmp_path)==[]
