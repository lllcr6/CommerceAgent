import json
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.api import observability
from app import usage_store

@pytest.fixture
async def client(tmp_path,monkeypatch):
    monkeypatch.setattr(usage_store,'PATH',tmp_path/'usage.sqlite')
    monkeypatch.setattr(observability,'RAG_REPORTS_DIR',tmp_path/'rag')
    monkeypatch.setattr(observability,'CALIB',tmp_path/'calib.json')
    app=FastAPI();app.include_router(observability.router)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        yield client

async def test_missing_data_is_safe_and_trend_has_no_job(client):
    result=(await client.get('/api/observability/overview')).json()
    assert not result['cost']['present']
    assert not result['trend']['present']
    assert 'job' not in result['trend']
    assert 'make' not in result['trend']
    assert result['agent_continue_job']['name']=='bench-agent-continue'

async def test_cost_reads_local_usage_and_not_saved_langfuse_report(client,monkeypatch):
    monkeypatch.setattr(usage_store,'intent_report',lambda:{'meta':{'source':'Local backend usage'},
      'rows':[{'intent':'product_question','tokens':120,'count':1,'input_tokens':100,'output_tokens':20}],
      'total_tokens':120,'total_requests':1})
    result=(await client.get('/api/observability/overview')).json()['cost']
    assert result['present']
    assert result['total_tokens']==120
    assert result['meta']['source']=='Local backend usage'
    assert 'job' not in result

async def test_trend_only_reads_completed_artifacts(client,monkeypatch):
    from app.rag_history import publish
    from types import SimpleNamespace
    def report(complete=True):
        return {'meta':{'status':'completed' if complete else 'partial','generated_at':'2026-10-22 01:00','n_samples':2,'relevance_version':'v1'},
          'retrieval':{'hybrid_rerank':{'overall':{'recall':1,'precision':1,'mrr':1}}},
          'generation':{'completion':{'complete':complete},'faithfulness':{'A':{'v':1,'answered':1}},'refusal':{'rate':1}}}
    (observability.RAG_REPORTS_DIR/'runs/complete/checkpoints').mkdir(parents=True)
    (observability.RAG_REPORTS_DIR/'runs/partial/checkpoints').mkdir(parents=True)
    publish(observability.RAG_REPORTS_DIR,SimpleNamespace(run_id='complete'),report(),'done')
    publish(observability.RAG_REPORTS_DIR,SimpleNamespace(run_id='partial'),report(False),'partial')
    result=(await client.get('/api/observability/overview')).json()['trend']
    assert [r['id'] for r in result['runs']]==['complete']
