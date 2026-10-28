import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import kb as kb_api
from app.db import repository

MD = """# 会员权益

## 运费与包邮

满 99 元包邮,未满收 10 元运费。偏远地区运费 20 元,不参与包邮。

## 发货时效

现货 48 小时内发货,预售按商品页标注的时间发。
"""


async def _noop() -> None:

    return None


async def _offline_milvus() -> dict:

    return {"online": False, "count": None, "detail": "stub"}


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(kb_api.router)
    return a


@pytest.fixture
async def client(app, db_session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_preview_is_dry_run(client):
    resp = await client.post("/api/kb/preview", json={"text": MD, "content_type": "policy"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["features"]["sections"] == 2
    assert body["chunks"][0]["section_path"] == "会员权益 / 运费与包邮"
    assert body["chunks"][0]["is_key_clause"] is True
    assert body["duplicates"] == 0 and body["dedup_known"] is True
    assert await repository.knowledge_stats() == {
        "total": 0, "pending": 0, "done": 0, "by_content_type": {}, "key_clause": 0}


async def test_preview_rejects_bad_input(client):
    assert (await client.post("/api/kb/preview", json={"text": "   "})).status_code == 400
    assert (await client.post(
        "/api/kb/preview", json={"text": MD, "content_type": "乱写"})).status_code == 400

    resp = await client.post("/api/kb/preview", json={"file": "../../etc/passwd"})
    assert resp.status_code == 400


async def test_ingest_then_reingest_is_idempotent(client):
    first = await client.post("/api/kb/ingest",
                             json={"text": MD, "content_type": "policy", "vectorize": False})
    assert first.status_code == 200
    body = first.json()
    assert body["inserted"] == 2 and body["skipped"] == 0
    assert body["vectorized"] is None
    stats = await repository.knowledge_stats()
    assert stats["total"] == 2 and stats["pending"] == 2 and stats["done"] == 0

    again = await client.post("/api/kb/ingest",
                              json={"text": MD, "content_type": "policy", "vectorize": False})
    assert again.json()["inserted"] == 0 and again.json()["skipped"] == 2
    assert (await repository.knowledge_stats())["total"] == 2


async def test_ingest_keeps_multiple_pieces_of_one_section(client):

    rows = "\n".join(f"| 型号 {i} | 参数 {i} | 备注 {i} |" for i in range(24))
    md = ("# 商品规格\n\n## 猫爬架\n\n| 型号 | 参数 | 备注 |\n|---|---|---|\n" + rows + "\n")
    resp = await client.post("/api/kb/ingest",
                             json={"text": md, "content_type": "spec", "vectorize": False})
    body = resp.json()
    assert body["chunks"] > 1
    assert body["inserted"] == body["chunks"] and body["skipped"] == 0
    pairs = await repository.list_chunk_pairs()
    assert len({q for q, _ in pairs}) == 1
    assert len(pairs) == body["chunks"]


async def test_vectorize_endpoint_uses_dualwrite(client, monkeypatch):

    called = {}

    async def fake(*a, **kw):
        called["hit"] = True
        return 7
    monkeypatch.setattr("app.kb.dualwrite.vectorize_pending", fake)
    monkeypatch.setattr(kb_api, "milvus_state", _offline_milvus)
    resp = await client.post("/api/kb/vectorize")
    assert resp.status_code == 200 and resp.json()["vectorized"] == 7 and called["hit"]


async def test_search_strategy_whitelist(client):
    assert (await client.post("/api/kb/search", json={"q": " "})).status_code == 400
    resp = await client.post("/api/kb/search", json={"q": "邮费是多少", "strategy": "玄学"})
    assert resp.status_code == 400


async def test_search_returns_hits(client, monkeypatch):
    async def fake(query, strategy="hybrid_rerank", top_k=None, **kw):
        assert (query, strategy, top_k) == ("邮费是多少", "vector", 3)
        return [{"id": 1, "question": "运费与包邮", "answer": "满 99 元包邮", "score": 0.83,
                 "section_path": "会员权益 / 运费与包邮", "content_type": "policy",
                 "category": "会员权益"}]
    monkeypatch.setattr("app.core.retrieval.search_knowledge", fake)
    resp = await client.post("/api/kb/search",
                             json={"q": "邮费是多少", "strategy": "vector", "top_k": 3})
    assert resp.status_code == 200
    hits = resp.json()["hits"]
    assert len(hits) == 1 and hits[0]["question"] == "运费与包邮"


async def test_overview_survives_milvus_offline(client, monkeypatch):

    monkeypatch.setattr(kb_api, "milvus_state", _offline_milvus)
    body = (await client.get("/api/kb/overview")).json()
    assert body["milvus"]["online"] is False
    assert body["consistent"] is None
    assert body["db_error"] is None
    assert [s["file"] for s in body["sources"]]
    assert {j["name"] for j in body["jobs"]} == set(kb_api.KB_JOBS)


async def test_source_ingestion_offers_incremental_reindex(client):

    body = (await client.get("/api/kb/overview")).json()
    jobs = {j["name"]: j for j in body["jobs"]}
    assert "kb-repatch" in jobs
    assert jobs["kb-repatch"]["cmd"] == "make kb-repatch"
    assert not jobs["kb-repatch"].get("heavy")
    assert "kb-reset" not in jobs  # Destructive maintenance is not exposed in the admin UI.


async def test_mined_drafts_require_human_approval(client, monkeypatch):

    sid = await repository.insert_staging("mine-t", "conv:1", "运费怎么算", "满99包邮")
    await repository.set_staging_status([sid], "kept")
    assert (await repository.knowledge_stats())["total"] == 0

    monkeypatch.setattr(kb_api.dualwrite, "vectorize_pending", lambda: _noop())
    resp = await client.post("/api/kb/staging/approve", json={"ids": [sid]})
    assert resp.status_code == 200 and resp.json()["approved"] == 1
    assert (await repository.knowledge_stats())["total"] == 1


async def test_duplicate_draft_approval_is_rejected(client, monkeypatch):

    monkeypatch.setattr(kb_api.dualwrite, "vectorize_pending", lambda: _noop())
    sid = await repository.insert_staging("mine-t", "conv:1", "运费怎么算", "满99包邮")
    await repository.set_staging_status([sid], "kept")

    assert (await client.post("/api/kb/staging/approve", json={"ids": [sid]})).status_code == 200
    again = await client.post("/api/kb/staging/approve", json={"ids": [sid]})
    assert again.status_code == 409
    assert (await repository.knowledge_stats())["total"] == 1


async def test_rejection_does_not_publish_knowledge(client):
    sid = await repository.insert_staging("mine-t", "conv:1", "老板微信多少", "不便透露")
    await repository.set_staging_status([sid], "kept")

    resp = await client.post("/api/kb/staging/reject", json={"ids": [sid]})
    assert resp.status_code == 200 and resp.json()["rejected"] == 1
    assert (await repository.knowledge_stats())["total"] == 0

    assert [r.status for r in await repository.list_staging_by_ids([sid])] == ["rejected"]
