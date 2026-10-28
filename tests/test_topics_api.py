import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import topics as topics_api
from app.db import repository


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr("app.config.settings.topic_classifier_enabled", True)
    a = FastAPI()
    a.include_router(topics_api.router)
    return a


@pytest.fixture
async def client(app, db_session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_distribution_empty_returns_all_17(client):
    resp = await client.get("/api/topics/distribution")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert len(body["classes"]) == 17


async def test_distribution_counts(client):
    qid = await repository.insert_low_confidence(None, "猫窝买大了想退", "retrieval_low_conf", None)
    await repository.insert_topic_classifications(
        [{"question_id": qid, "labels": ["size_fit", "returns_refunds"]}])
    resp = await client.get("/api/topics/distribution")
    body = resp.json()
    by_label = {c["label"]: c for c in body["classes"]}
    assert body["total"] == 1
    assert by_label["size_fit"]["count"] == 1 and by_label["returns_refunds"]["count"] == 1
    assert by_label["delivery_tracking"]["count"] == 0


async def test_distribution_samples_are_deduped(client):

    for _ in range(3):
        qid = await repository.insert_low_confidence(None, "废砂盒多久倒", "retrieval_low_conf", None)
        await repository.insert_topic_classifications([{"question_id": qid, "labels": ["product_information"]}])

    body = (await client.get("/api/topics/distribution")).json()
    card = {c["label"]: c for c in body["classes"]}["product_information"]
    assert card["count"] == 3 and card["samples"] == ["废砂盒多久倒"]


async def _classify(text: str, labels: list[str]) -> int:
    qid = await repository.insert_low_confidence(None, text, "retrieval_low_conf", None)
    await repository.insert_topic_classifications([{"question_id": qid, "labels": labels}])
    return qid


async def test_questions_paginates_within_one_class(client):

    for i in range(7):
        await _classify(f"猫窝能不能机洗 {i}", ["product_information"])

    body = (await client.get("/api/topics/questions?label=product_information&size=3&page=2")).json()
    assert body["total"] == 7 and body["pages"] == 3 and body["page"] == 2
    assert len(body["items"]) == 3
    tail = (await client.get("/api/topics/questions?label=product_information&size=3&page=3")).json()
    assert len(tail["items"]) == 1


async def test_questions_of_multi_label_show_in_every_hit_class(client):

    await _classify("猫窝买大了想退", ["size_fit", "returns_refunds"])

    for label in ("size_fit", "returns_refunds"):
        body = (await client.get(f"/api/topics/questions?label={label}")).json()
        assert body["total"] == 1
        assert body["items"][0]["labels"] == ["size_fit", "returns_refunds"]
        assert body["items"][0]["text"] == "猫窝买大了想退"


async def test_questions_falls_back_to_raw_when_not_merged(client):

    await _classify("那个猫窝啊到底能不能机洗啊", ["product_information"])

    item = (await client.get("/api/topics/questions?label=product_information")).json()["items"][0]
    assert item["text"] == "那个猫窝啊到底能不能机洗啊"
    assert item["normalized"] is False and item["review_status"] is None
    assert item["source"] == "retrieval_low_conf"


async def test_questions_uses_normalized_text_after_merge(client):

    qid = await _classify("那个猫窝啊到底能不能机洗啊", ["product_information"])
    rid = await repository.insert_review_item("猫窝能不能机洗", "分内胆与外套…")
    await repository.set_matched_review(qid, rid)

    item = (await client.get("/api/topics/questions?label=product_information")).json()["items"][0]
    assert item["text"] == "猫窝能不能机洗" and item["normalized"] is True
    assert item["raw_question"] == "那个猫窝啊到底能不能机洗啊"
    assert item["review_status"] == "pending"


async def test_unknown_label_is_rejected(client):

    resp = await client.get("/api/topics/questions?label=不存在的类")
    assert resp.status_code == 400
    assert "Unknown topic" in resp.json()["detail"]
