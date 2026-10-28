import pytest

from app.kb.evaluation import (fingerprint, retrieval_metrics, validate_annotations,
                               validate_live_chunks)


def sample(ids):
    return {"id": "Q1", "bucket": "A_policy", "should_refuse": False,
            "relevance_version": "chunk-id-v1", "relevant_chunk_ids": ids}


def chunk(cid, answer="正确证据"):
    row = {"id": cid, "section_path": "同一个标题", "question": "问题",
           "answer": answer, "content_type": "manual"}
    return {**row, "sha256": fingerprint(row)}


def test_same_title_wrong_id_is_not_relevant():
    # The two actual processing-time chunks have the same title but different rows.
    hits = [{"id": 26, "section_path": "售后手册 / 常见问题处理时限"}]
    assert retrieval_metrics(hits, sample([25])) == {"recall": 0, "precision": 0, "mrr": 0}


def test_standard_chunk_recall_precision_and_first_hit_mrr():
    hits = [{"id": cid} for cid in [99, 20, 25, 98, 97, 30]]
    assert retrieval_metrics(hits, sample([20, 25, 30])) == {
        "recall": 2 / 3, "precision": 2 / 5, "mrr": 1 / 2}


def test_duplicates_do_not_inflate_metrics_and_short_results_still_divide_by_k():
    assert retrieval_metrics([{"id": 20}, {"id": 20}], sample([20, 25])) == {
        "recall": 0.5, "precision": 0.2, "mrr": 1.0}


def test_only_first_ten_results_count_for_mrr():
    assert retrieval_metrics([{"id": n} for n in range(1, 12)], sample([11]))["mrr"] == 0


def test_missing_id_labels_never_fall_back_to_title_matching():
    old = {"id": "Q1", "expect_section": ["同一个标题"], "should_refuse": False}
    with pytest.raises(ValueError, match="chunk ID"):
        validate_annotations([old], [chunk(1)])


def test_rebuild_changed_id_or_changed_content_requires_review():
    snapshot = [chunk(1)]
    with pytest.raises(ValueError, match="mismatch"):
        validate_live_chunks([sample([1])], snapshot, [chunk(2)])
    with pytest.raises(ValueError, match="mismatch"):
        validate_live_chunks([sample([1])], snapshot, [chunk(1, "同 ID 的不同内容")])
    validate_live_chunks([sample([1])], snapshot, [chunk(1), chunk(2)])


def test_tampered_snapshot_is_rejected():
    snapshot = [chunk(1)]
    snapshot[0]["answer"] = "改过的内容"
    with pytest.raises(ValueError, match="fingerprint"):
        validate_annotations([sample([1])], snapshot)


@pytest.mark.parametrize("ids", [[1, 1], ["1"], [True], [999]])
def test_invalid_or_unknown_ids_are_rejected(ids):
    with pytest.raises(ValueError):
        validate_annotations([sample(ids)], [chunk(1)])


def test_answerable_question_cannot_be_mislabeled_as_out_of_kb():
    row = sample([1])
    row.update(bucket="D_absent", should_refuse=True)
    with pytest.raises(ValueError):
        validate_annotations([row], [chunk(1)])


async def test_eval_runner_aggregates_chunk_metrics(monkeypatch):
    from scripts import eval_rag

    async def retrieve(strategy, row):
        return [{"id": 26, "section_path": "同一个标题", "question": "", "answer": ""},
                {"id": 25, "section_path": "同一个标题", "question": "退款时限", "answer": "3 天"}]

    monkeypatch.setattr(eval_rag, "_retrieve", retrieve)
    monkeypatch.setattr(eval_rag, "STRATEGIES", ["bm25"])
    row = {**sample([25]), "query": "退款时限", "expect_points": ["3 天"]}
    result, _, _ = await eval_rag._deterministic([row])
    assert result["bm25"]["overall"] == {"recall": 1, "precision": 0.2, "mrr": 0.5, "ndcg":0.631}
