import json

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import acceptance, kb, rageval
from app.topic_schema import LABEL2ID
from app.paths import RAG_EVAL_FILE, ROBERTA_DATASET_DIR
from scripts.eval_rag import _load


async def test_data_page_reads_splits_outside_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.include_router(acceptance.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/acceptance/data")
    assert response.status_code == 200
    splits = response.json()["dataset"]["splits"]
    for name in ("train", "val", "test"):
        rows = [json.loads(line) for line in (ROBERTA_DATASET_DIR / f"{name}.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows and splits[name]["size"] == len(rows)
        assert splits[name]["file"]["present"]
        assert all(row["text"] and row["labels"] and set(row["labels"]) <= LABEL2ID.keys()
                   for row in rows)


def test_rag_eval_reads_questions_outside_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    samples = _load()
    assert samples
    assert len(samples) == len(RAG_EVAL_FILE.read_text(encoding="utf-8").splitlines())
    report = tmp_path / "rag_eval.json"
    report.write_text(json.dumps({"meta": {"n_samples": len(samples)}}))
    monkeypatch.setattr(rageval, "REPORT", report)
    assert rageval._read()["meta"]["n_samples"] == len(samples)


async def test_knowledge_preview_reads_documents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def no_existing_chunks():
        return set()
    monkeypatch.setattr(kb, "_existing_fingerprints", no_existing_chunks)
    app = FastAPI()
    app.include_router(kb.router)
    materials = kb._sources()
    assert len(materials) == 6
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for item in materials:
            response = await client.post("/api/kb/preview", json={"file": item["file"]})
            assert response.status_code == 200
            body = response.json()
            assert body["total"] > 0
            assert body["source"] == item["path"]
