import re
import pathlib

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import jobs as jobs_api
from app.core import jobs


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(jobs_api.router)
    return a


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_unknown_job_is_rejected(client):

    for path, method in (("/api/jobs/rm -rf", "post"), ("/api/jobs/rm -rf", "get"),
                         ("/api/jobs/未注册/stop", "post")):
        resp = await getattr(client, method)(path)
        assert resp.status_code == 404, path
        assert "Unknown job" in resp.json()["detail"]


async def test_running_job_refuses_reentry(client, monkeypatch):

    monkeypatch.setitem(jobs._runs, "kb-build",
                        jobs.JobRun(status="running", pid=4242))
    resp = await client.post("/api/jobs/kb-build")
    assert resp.status_code == 409 and "already running" in resp.json()["detail"]


async def test_status_all_covers_registry(client):
    body = (await client.get("/api/jobs")).json()
    assert {j["name"] for j in body["jobs"]} == set(jobs.JOBS)
    for j in body["jobs"]:
        assert j["cmd"].startswith("make ")


def test_every_job_target_exists_in_makefile():
    text = (pathlib.Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
    targets = set(re.findall(r"^([a-zA-Z0-9_.-]+):", text, re.MULTILINE))
    missing = [spec.argv[1] for spec in jobs.JOBS.values() if spec.argv[1] not in targets]
    assert not missing, f"作业指向的 make 目标不存在:{missing}"


def test_job_titles_and_requirements_are_english():
    import re
    from app.core.jobs import JOBS
    for spec in JOBS.values():
        assert not re.search(r"[\u3400-\u9fff]", spec.title + spec.needs), spec.name


async def test_agent_job_can_start_and_poll_using_the_shared_job_api(client,monkeypatch):
    started=[]
    async def start(name):
        started.append(name)
        monkeypatch.setitem(jobs._runs,name,jobs.JobRun(status='running',pid=4243))
    monkeypatch.setattr(jobs,'start',start)
    response=await client.post('/api/jobs/bench-agent')
    assert response.status_code==200
    assert response.json()['status']=='running'
    assert started==['bench-agent']
    assert (await client.get('/api/jobs/bench-agent')).json()['status']=='running'
    assert jobs.JOBS['bench-agent'].argv==('make','bench-agent')


@pytest.mark.parametrize('name',['eval-rag','bench-agent','eval-flywheel','roberta-eval','cost-report','calibrate-confidence'])
async def test_evaluation_stop_endpoint_terminates_the_owned_process_group(client,monkeypatch,name):
    class Process:
        pid=4244
        async def wait(self):return -15
    signals=[]
    monkeypatch.setattr(jobs.os,'getpgid',lambda pid:4244)
    monkeypatch.setattr(jobs.os,'killpg',lambda group,sig:signals.append((group,sig)))
    monkeypatch.setitem(jobs._runs,name,jobs.JobRun(status='running',pid=4244,proc=Process()))
    response=await client.post('/api/jobs/'+name+'/stop')
    assert response.status_code==200
    assert response.json()['status']=='stopped'
    assert signals==[(4244,jobs.signal.SIGTERM)]
    assert (await client.post('/api/jobs/'+name+'/stop')).status_code==409


def test_knowledge_reset_targets_configured_index():
    from pathlib import Path
    recipe = Path('Makefile').read_text().split('\nkb-reset:\n', 1)[1].split('\n\n', 1)[0]
    assert 'm.drop(m.get_client(), m.COLLECTION)' in recipe


async def test_destructive_knowledge_reset_is_not_available_over_http(client, monkeypatch):
    from unittest.mock import AsyncMock
    from app.core import jobs
    start = AsyncMock()
    monkeypatch.setattr(jobs, 'start', start)
    for method, path in [('GET','/api/jobs/kb-reset'),('POST','/api/jobs/kb-reset'),('POST','/api/jobs/kb-reset/stop')]:
        assert (await client.request(method, path)).status_code == 404
    assert 'kb-reset' not in {j['name'] for j in (await client.get('/api/jobs')).json()['jobs']}
    start.assert_not_awaited()


@pytest.mark.parametrize('name,other', [('eval-rag','eval-rag-continue'), ('eval-rag-continue','eval-rag')])
async def test_rag_fresh_and_continue_cannot_overlap(client, monkeypatch, name, other):
    monkeypatch.setitem(jobs._runs, other, jobs.JobRun(status='running', pid=123))
    response = await client.post('/api/jobs/' + name)
    assert response.status_code == 409
    assert 'already running' in response.json()['detail']


def test_continue_job_uses_fixed_resume_argument():
    assert jobs.JOBS['eval-rag-continue'].argv == ('make', 'eval-rag', 'CONTINUE=1')
