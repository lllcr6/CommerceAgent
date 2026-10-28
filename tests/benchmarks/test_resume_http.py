import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest

from scripts.benchmarks import agent_performance as agent


async def test_cancelled_request_reuses_server_result_and_completed_turns(tmp_path,monkeypatch):
    import app.agent_resume as resume
    from app.kb import evaluation
    from scripts import eval_rag
    monkeypatch.setattr(evaluation,'check_live_annotations',AsyncMock(return_value=[]))
    monkeypatch.setattr(eval_rag,'_load',lambda:[])
    monkeypatch.setattr(resume,'signature',lambda:'same')
    monkeypatch.setattr(agent,'business_fingerprint',lambda:'same')
    monkeypatch.setattr(agent,'ROOT',tmp_path)
    monkeypatch.setattr(agent,'SCENARIOS',[('sample',['one','two','three'],[['ok']]*3)])
    pricing=tmp_path/'data/benchmarks/pricing.json';pricing.parent.mkdir(parents=True);pricing.write_text('{"models":{}}')
    def write(name,data):
        path=tmp_path/'data/benchmarks'/(name+'.json');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data));return path
    monkeypatch.setattr(agent,'write_report',write)
    monkeypatch.setattr(agent,'collect_usage',AsyncMock(return_value={}))
    monkeypatch.setattr(agent.asyncio,'sleep',AsyncMock())
    provider_calls=[];request_ids=[];cached={};cancelled=False
    def handler(request):
        nonlocal cancelled
        if request.url.path == '/openapi.json':
            return httpx.Response(200, json={'paths': {
                '/api/benchmark/conversations': {'post': {}},
                '/api/conversations/{cid}/generation': {'get': {}},
                '/api/chat': {'post': {'parameters': [
                    {'in': 'header', 'name': 'X-Benchmark-Request'}]}}}})
        if request.url.path in ['/api/auth/register','/api/auth/login']:
            return httpx.Response(200,json={})
        if request.url.path=='/api/benchmark/conversations':
            return httpx.Response(200,json={'conversation_id':11})
        if request.url.path=='/api/conversations/11/generation':
            return httpx.Response(200,json={'run_id':request_ids[-1],'state':'completed'})
        assert request.url.path=='/api/chat'
        payload=json.loads(request.content);key=request.headers['X-Benchmark-Request'];request_ids.append(key)
        if key not in cached:
            provider_calls.append(payload['message'])
            cached[key]='data: '+json.dumps({'delta':'ok'})+'\n\ndata: '+json.dumps({'event':'done','conversation_id':11})+'\n\n'
        if payload['message']=='two' and not cancelled:
            cancelled=True
            raise asyncio.CancelledError()
        return httpx.Response(200,text=cached[key],headers={'content-type':'text/event-stream'})
    client_type=httpx.AsyncClient
    monkeypatch.setattr(agent.httpx,'AsyncClient',lambda **kw:client_type(**kw,transport=httpx.MockTransport(handler)))
    args=SimpleNamespace(base_url='http://test',scenario=None,repeats=1,concurrency=1,output='agent_runs/test/agent_performance',resume=False)
    with pytest.raises(asyncio.CancelledError):await agent.main(args)
    saved=json.loads((tmp_path/'data/benchmarks/agent_runs/test/agent_performance.json').read_text())
    assert len(saved['sessions'][0]['turns'])==1
    assert saved['sessions'][0]['pending']['turn']==2
    args.resume=True
    await agent.main(args)
    result=json.loads((tmp_path/'data/benchmarks/agent_runs/test/agent_performance.json').read_text())
    assert provider_calls==['one','two','three']
    assert request_ids[1]==request_ids[2]  # Same request, same server producer.
    assert len(result['sessions'][0]['turns'])==3
    assert result['sessions'][0]['turns'][1]['recovered']
    assert result['sessions'][0]['turns'][1]['latency_ms'] is None
    before=len(request_ids)
    await agent.main(args)
    assert len(request_ids)==before
    monkeypatch.setattr(resume,'signature',lambda:'changed')
    with pytest.raises(ValueError,match='changed'):await agent.main(args)
    assert len(request_ids)==before
