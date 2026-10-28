import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import rageval as rageval_api
from app.db import repository

CITS = [{"n": 1, "chunk_id": 141, "section_path": "退货退款政策 / 退换货运费承担",
         "question": "退换货运费承担", "answer": "无理由退货的退回运费由买家承担…"},
        {"n": 2, "chunk_id": 140, "section_path": "退货退款政策 / 换货政策 / 换货运费",
         "question": "换货运费", "answer": "非质量问题的换货,往返运费由买家承担…"}]


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(rageval_api.router)
    return a


@pytest.fixture
async def client(app, db_session_factory):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _add(eval_id="A43", **kw):
    kw.setdefault("bucket", "A_policy")
    kw.setdefault("query", "少发漏发导致的退换货,运费由谁承担")
    kw.setdefault("answer", "换货往返运费也由平台承担[3]。")
    kw.setdefault("reason", "证据区分了非质量问题由买家承担,客服遗漏条件范围。")
    return await repository.upsert_faith_case(eval_id, **kw)


async def test_first_faithfulness_case_is_unresolved(client):
    cid, reopened = await _add(citations=CITS)
    assert reopened is False
    d = (await client.get("/api/rag-eval/faith-cases")).json()
    assert d["counts"]["unresolved"] == 1 and d["total"] == 1
    item = d["items"][0]
    assert item["id"] == cid and item["status"] == "unresolved" and item["seen_count"] == 1

    assert [c["n"] for c in item["citations"]] == [1, 2]
    assert item["citations"][1]["section_path"].endswith("换货运费")


async def test_repeated_case_increments_count_without_duplicate_row(client):
    await _add()
    await _add(answer="第二版答案", reason="第二次理由")
    d = (await client.get("/api/rag-eval/faith-cases")).json()
    assert d["total"] == 1
    item = d["items"][0]
    assert item["seen_count"] == 2 and item["answer"] == "第二版答案"


async def test_reviewed_case_recurrence_reopens_case(client):
    cid, _ = await _add()
    r = await client.post(f"/api/rag-eval/faith-cases/{cid}/status", json={"status": "resolved", "resolution": "库里补了那一格"})
    assert r.json()["status"] == "resolved" and r.json()["reopened"] is False
    _, reopened = await _add(answer="又编了")
    assert reopened is True
    item = (await client.get("/api/rag-eval/faith-cases")).json()["items"][0]
    assert item["status"] == "unresolved" and item["reopened"] is True


async def test_historical_case_without_snapshot_has_empty_citations(client):
    await _add()
    item = (await client.get("/api/rag-eval/faith-cases")).json()["items"][0]
    assert not item["citations"]


async def test_case_status_filter_and_pagination(client):
    for i in range(7):
        await _add(f"X{i}")
    cid, _ = await _add("Y1")
    await client.post(f"/api/rag-eval/faith-cases/{cid}/status", json={"status": "dismissed", "resolution": "裁判判严了,答案没错"})

    d = (await client.get("/api/rag-eval/faith-cases?size=5&page=1")).json()
    assert d["total"] == 8 and d["pages"] == 2 and len(d["items"]) == 5
    assert all(i["status"] == "unresolved" for i in d["items"][:5])
    d2 = (await client.get("/api/rag-eval/faith-cases?size=5&page=2")).json()
    assert len(d2["items"]) == 3

    only = (await client.get("/api/rag-eval/faith-cases?status=dismissed")).json()
    assert only["total"] == 1 and only["items"][0]["eval_id"] == "Y1"
    assert only["counts"] == {"unresolved": 7, "resolved": 0, "dismissed": 1}


async def test_reopening_clears_resolution_timestamp(client):
    cid, _ = await _add()
    await client.post(f"/api/rag-eval/faith-cases/{cid}/status", json={"status": "resolved", "resolution": "库里补了那一格"})
    back = (await client.post(f"/api/rag-eval/faith-cases/{cid}/status",
                              json={"status": "unresolved"})).json()
    assert back["status"] == "unresolved" and back["resolved_at"] is None and back["reopened"] is False


async def test_final_review_requires_explanation(client):

    cid, _ = await _add()
    for st in ("resolved", "dismissed"):
        r = await client.post(f"/api/rag-eval/faith-cases/{cid}/status", json={"status": st})
        assert r.status_code == 400
        blank = await client.post(f"/api/rag-eval/faith-cases/{cid}/status",
                                  json={"status": st, "resolution": "   "})
        assert blank.status_code == 400
    item = (await client.get("/api/rag-eval/faith-cases")).json()["items"][0]
    assert item["status"] == "unresolved"


async def test_review_notes_are_persisted_and_returned(client):
    cid, _ = await _add()
    r = await client.post(f"/api/rag-eval/faith-cases/{cid}/status",
                          json={"status": "resolved", "resolution": "库里给 Lite 补了废砂盒容量约 5 天"})
    assert r.json()["resolution"] == "库里给 Lite 补了废砂盒容量约 5 天"
    item = (await client.get("/api/rag-eval/faith-cases?status=resolved")).json()["items"][0]
    assert item["resolution"].startswith("库里给 Lite")


async def test_reopening_clears_review_notes(client):
    cid, _ = await _add()
    await client.post(f"/api/rag-eval/faith-cases/{cid}/status",
                      json={"status": "dismissed", "resolution": "常识类,不进库"})
    back = (await client.post(f"/api/rag-eval/faith-cases/{cid}/status",
                              json={"status": "unresolved"})).json()
    assert back["resolution"] is None and back["resolved_at"] is None


async def test_flagged_and_confirmed_hallucination_rates(client, monkeypatch):

    monkeypatch.setattr(rageval_api, "_read", lambda: {
        "generation": {"faithfulness": {"A_policy": {"answered": 60}, "B_model": {"answered": 40}},
                       "refusal": {"total": 20, "correct": 18},
                       "faithfulness_cases": [{"id": f"H{i}"} for i in range(4)]}})
    for i in range(4):
        await _add(f"H{i}")
    ids = [i["id"] for i in (await client.get("/api/rag-eval/faith-cases")).json()["items"]]
    await client.post(f"/api/rag-eval/faith-cases/{ids[0]}/status",
                      json={"status": "resolved", "resolution": "库里补了那一格"})
    await client.post(f"/api/rag-eval/faith-cases/{ids[1]}/status",
                      json={"status": "dismissed", "resolution": "裁判判严了"})
    h = (await client.get("/api/rag-eval/faith-cases")).json()["hallucination"]
    assert h["evaluated"] == 120 and h["graded"] == 100 and h["absent"] == 20
    assert h["refusal_missed"] == 2
    assert h["cases_judged"] == 4 and h["cases_confirmed"] == 1
    assert h["dismissed"] == 1 and h["pending"] == 2
    assert h["judged"] == 6 and h["judged_rate"] == 0.05
    assert h["confirmed"] == 3 and h["confirmed_rate"] == 0.025
    assert h["ledger"] == {"total": 4, "unresolved": 2, "resolved": 1, "dismissed": 1}


async def test_run_rates_exclude_cumulative_ledger_totals(client, monkeypatch):


    monkeypatch.setattr(rageval_api, "_read", lambda: {
        "generation": {"faithfulness": {"A_policy": {"answered": 240}},
                       "refusal": {"total": 60, "correct": 60},
                       "faithfulness_cases": [{"id": "A30"}]}})
    for eid in ("C2", "E15", "A30"):
        await _add(eid)
    ids = {i["eval_id"]: i["id"] for i in (await client.get("/api/rag-eval/faith-cases")).json()["items"]}
    for eid in ("C2", "E15"):
        await client.post(f"/api/rag-eval/faith-cases/{ids[eid]}/status",
                          json={"status": "resolved", "resolution": "库里补了那一格"})

    h = (await client.get("/api/rag-eval/faith-cases")).json()["hallucination"]
    assert h["cases_judged"] == 1 and h["judged"] == 1
    assert h["judged_rate"] == round(1 / 300, 4)
    assert h["pending"] == 1 and h["dismissed"] == 0
    assert h["cases_confirmed"] == 0 and h["confirmed_rate"] == 0.0

    assert h["ledger"] == {"total": 3, "unresolved": 1, "resolved": 2, "dismissed": 0}


async def test_unsupported_answer_counts_as_confirmed_hallucination(client, monkeypatch):

    monkeypatch.setattr(rageval_api, "_read", lambda: {
        "generation": {"faithfulness": {"A_policy": {"answered": 60}},
                       "refusal": {"total": 60, "correct": 57}}})
    h = (await client.get("/api/rag-eval/faith-cases")).json()["hallucination"]
    assert h["cases_judged"] == 0 and h["refusal_missed"] == 3
    assert h["evaluated"] == 120 and h["confirmed"] == 3 and h["confirmed_rate"] == 0.025


async def test_missing_report_has_no_rate_denominator(client, monkeypatch):


    monkeypatch.setattr(rageval_api, "_read", lambda: None)
    await _add()
    h = (await client.get("/api/rag-eval/faith-cases")).json()["hallucination"]
    assert h["evaluated"] is None and h["confirmed_rate"] is None and h["judged_rate"] is None
    assert h["judged"] == 0
    assert h["ledger"]["total"] == 1


async def test_invalid_status_and_missing_case(client):
    assert (await client.get("/api/rag-eval/faith-cases?status=瞎写")).status_code == 400
    r = await client.post("/api/rag-eval/faith-cases/99999/status", json={"status": "resolved", "resolution": "库里补了那一格"})
    assert r.status_code == 404
    cid, _ = await _add()
    bad = await client.post(f"/api/rag-eval/faith-cases/{cid}/status", json={"status": "关闭"})
    assert bad.status_code == 422
