import json
import hashlib
from app.paths import RAG_EVAL_FILE

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import rageval

REPORT = {
    "meta": {"dataset_sha256": hashlib.sha256(RAG_EVAL_FILE.read_bytes()).hexdigest(), "n_samples": 80, "kb_chunks": 51, "chat_model": "gpt-5.5",
             "generated_at": "2026-07-29 01:20"},
    "retrieval": {
        "vector": {"C_colloquial": {"recall": 1.0, "mrr": 0.887},
                   "overall": {"recall": 1.0, "mrr": 0.943}},
        "bm25": {"C_colloquial": {"recall": 0.75, "mrr": 0.557},
                 "overall": {"recall": 0.917, "mrr": 0.824}},
        "hybrid": {"overall": {"recall": 0.967, "mrr": 0.873}},
        "hybrid_rerank": {"overall": {"recall": 1.0, "mrr": 0.972}},
    },
    "evidence_coverage": {"vector": {"overall": 1.0}, "bm25": {"overall": 0.95},
                          "hybrid": {"overall": 0.983}, "hybrid_rerank": {"overall": 1.0}},
    "generation": {"answer_coverage": {"hybrid_rerank": {"overall": 1.0}},
                   "faithfulness": {"A_policy": {"v": 1.0, "answered": 20}},
                   "faithfulness_cases": [], "refusal": {"rate": 1.0, "total": 20, "correct": 20},
                   "skipped": 0},
}


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(rageval.router)
    return a


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.fixture
def report(tmp_path, monkeypatch):

    p = tmp_path / "rag_eval.json"
    monkeypatch.setattr(rageval, "REPORT", p)
    monkeypatch.setattr(rageval, "TEXT_LOG", p.with_name("rag_eval.txt"))
    return p


async def test_missing_report_is_a_state_not_an_error(client, report):

    body = (await client.get("/api/rag-eval/overview")).json()
    assert body["present"] is False
    assert body["make"] == "make eval-rag"
    assert body["job"]["specs"][0]["name"] == "eval-rag"
    assert body["job"]["artifacts"]["json"]["present"] is False


async def test_overview_reads_the_artifact_verbatim(client, report):

    report.write_text(json.dumps(REPORT, ensure_ascii=False), encoding="utf-8")

    body = (await client.get("/api/rag-eval/overview")).json()
    assert body["present"] is True
    assert body["retrieval"] == REPORT["retrieval"]
    assert body["evidence_coverage"] == REPORT["evidence_coverage"]
    assert body["meta"]["n_samples"] == 80
    assert body["job"]["artifacts"]["json"]["present"] is True


async def test_best_strategy_is_the_top_overall_mrr(client, report):

    data = json.loads(json.dumps(REPORT))
    data["retrieval"]["vector"]["overall"]["mrr"] = 0.99
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    body = (await client.get("/api/rag-eval/overview")).json()
    assert body["best"] == {"strategy": "vector", "mrr": 0.99}


async def test_read_notes_pass_through_and_default_to_empty(client, report):

    data = json.loads(json.dumps(REPORT))
    data["read_notes"] = {"rag_mrr": "型号桶纯向量只有 0.55,认错了型号"}
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    body = (await client.get("/api/rag-eval/overview")).json()
    assert body["read_notes"]["rag_mrr"] == "型号桶纯向量只有 0.55,认错了型号"

    report.write_text(json.dumps(REPORT, ensure_ascii=False), encoding="utf-8")
    assert (await client.get("/api/rag-eval/overview")).json()["read_notes"] == {}


async def test_generation_missing_keeps_retrieval_half(client, report):

    data = json.loads(json.dumps(REPORT))
    data["generation"] = None
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    body = (await client.get("/api/rag-eval/overview")).json()
    assert body["present"] is True
    assert body["generation_done"] is False
    assert body["retrieval"]["hybrid_rerank"]["overall"]["mrr"] == 0.972


async def test_old_report_is_labeled_legacy_and_precision_is_not_invented(client, report):
    report.write_text(json.dumps(REPORT), encoding="utf-8")
    body = (await client.get("/api/rag-eval/overview")).json()
    assert body["relevance"]["needs_rerun"] is True
    assert body["relevance"]["report_version"] == "section-match-legacy"
    assert "precision" not in body["retrieval"]["hybrid_rerank"]["overall"]


async def test_chunk_id_report_passes_through_precision(client, report):
    data = json.loads(json.dumps(REPORT))
    data["meta"]["relevance_version"] = "chunk-id-v1"
    data["retrieval"]["hybrid_rerank"]["overall"]["precision"] = 0.4
    report.write_text(json.dumps(data), encoding="utf-8")
    body = (await client.get("/api/rag-eval/overview")).json()
    assert body["relevance"]["needs_rerun"] is False
    assert body["retrieval"]["hybrid_rerank"]["overall"]["precision"] == 0.4


async def test_broken_report_reads_as_missing(client, report):

    report.write_text("{半个 json", encoding="utf-8")

    body = (await client.get("/api/rag-eval/overview")).json()
    assert body["present"] is False


async def test_report_from_another_corpus_is_not_presented_as_english(client, report):
    data = json.loads(json.dumps(REPORT))
    data['meta']['dataset_sha256'] = 'old-chinese-corpus'
    report.write_text(json.dumps(data))
    body = (await client.get('/api/rag-eval/overview')).json()
    assert body['present'] is False and body['stale'] is True
    assert 'retrieval' not in body
