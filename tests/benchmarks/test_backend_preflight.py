import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from scripts.benchmarks import agent_performance as agent
from scripts.benchmarks import run_agent_evaluation as runner


def capabilities():
    return {'paths': {
        '/api/benchmark/conversations': {'post': {}},
        '/api/conversations/{cid}/generation': {'get': {}},
        '/api/chat': {'post': {'parameters': [{'in': 'header', 'name': 'X-Benchmark-Request'}]}}}}


@pytest.mark.parametrize('failure', ['missing_route', 'missing_replay', 'offline'])
async def test_preflight_failure_preserves_selected_run_and_sends_only_read(tmp_path, monkeypatch, failure):
    pointer=tmp_path/'agent_runs/current.json'
    pointer.parent.mkdir()
    pointer.write_text(json.dumps({'output':'agent_runs/existing/agent_performance'}))
    before={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(runner,'OUT',tmp_path)
    calls=[]
    def handle(request):
        calls.append((request.method,request.url.path))
        assert request.method=='GET' and request.url.path=='/openapi.json'
        if failure=='offline': raise httpx.ConnectError('offline',request=request)
        schema=capabilities()
        if failure=='missing_route': del schema['paths']['/api/benchmark/conversations']
        else: schema['paths']['/api/chat']['post']['parameters']=[]
        return httpx.Response(200,json=schema)
    original=httpx.AsyncClient
    monkeypatch.setattr(agent.httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    run=AsyncMock(side_effect=AssertionError('Must not create accounts or call models'))
    monkeypatch.setattr(agent,'main',run)
    args=SimpleNamespace(base_url='http://test',resume=False)
    with pytest.raises(agent.BenchmarkBackendUnavailable): await runner.run(args)
    assert calls==[('GET','/openapi.json')]
    assert before=={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    run.assert_not_called()


async def test_available_backend_preflight_is_read_only(monkeypatch):
    calls=[]
    def handle(request):
        calls.append((request.method,request.url.path))
        return httpx.Response(200,json=capabilities())
    original=httpx.AsyncClient
    monkeypatch.setattr(agent.httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    await agent.check_backend('http://test')
    assert calls==[('GET','/openapi.json')]
