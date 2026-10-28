import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import admin as admin_api

CARDS = ("kb", "rageval", "review", "observability", "topics", "classifier")


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(admin_api.router)
    return a


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.fixture(autouse=True)
def _no_milvus(monkeypatch):
    async def offline():
        return {"online": False, "count": None, "detail": "stub"}
    monkeypatch.setattr("app.api.kb.milvus_state", offline)


async def test_all_deps_down_still_returns_every_card(client, monkeypatch):

    async def boom(*a, **kw):
        raise RuntimeError("Database unavailable")
    for fn in ("knowledge_stats", "list_review_queue", "topic_distribution", "list_eval_runs"):
        monkeypatch.setattr(f"app.db.repository.{fn}", boom)

    body = (await client.get("/api/admin/overview")).json()
    assert [m["key"] for m in body["modules"]] == list(CARDS)
    for key in ("kb", "review"):
        m = {c["key"]: c for c in body["modules"]}[key]
        assert m["status"] == "error" and "Database unavailable" in m["note"]


async def test_empty_db_reads_as_missing_not_error(client, db_session_factory):

    body = (await client.get("/api/admin/overview")).json()
    by_key = {m["key"]: m for m in body["modules"]}
    assert by_key["kb"]["status"] == "missing"
    assert by_key["review"]["status"] == "missing"
    assert by_key["topics"]["status"] == "missing"
    assert by_key["kb"]["page"] == "/kb"


async def test_topics_headline_ranks_by_count(client, monkeypatch):

    async def dist(*a, **kw):
        return {"total": 9, "latest": None, "classes": [
            {"label": "returns_refunds", "count": 1, "samples": []},
            {"label": "delivery_tracking", "count": 3, "samples": []},
            {"label": "product_information", "count": 5, "samples": []},
            {"label": "reviews_feedback", "count": 0, "samples": []},
        ]}
    monkeypatch.setattr("app.db.repository.topic_distribution", dist)
    monkeypatch.setattr(admin_api.settings, "topic_classifier_enabled", True)

    body = (await client.get("/api/admin/overview")).json()
    card = {m["key"]: m for m in body["modules"]}["topics"]
    assert card["headline"] == "Top categories: product_information 5, delivery_tracking 3, returns_refunds 1"


@pytest.mark.parametrize('refusal,expected', [({'rate':None}, '—'), ({}, '—'), (None, '—'), ({'rate':0}, '0%'), ({'rate':0.85}, '85%')])
async def test_partial_refusal_results_do_not_break_admin_overview(client, monkeypatch, refusal, expected):
    async def report():
        return {'present':True,'best':{'strategy':'vector','mrr':0.85},
                'generation':{'refusal':refusal},'generation_done':True,'meta':{'n_samples':121}}
    monkeypatch.setattr(admin_api.rageval,'overview',report)
    async def other():
        return {'status':'ok'}
    for name in ('_kb_card','_review_card','_observability_card','_topics_card','_classifier_card'):
        monkeypatch.setattr(admin_api,name,other)
    response=await client.get('/api/admin/overview')
    assert response.status_code==200
    card=response.json()['modules'][1]
    assert card['metrics'][0]['value']=='0.850'
    assert card['metrics'][2]['value']==expected
    assert card['status']==('attention' if expected=='—' else 'ok')
