import pytest

from app.core.confidence import EvidenceConfidence, compute_evidence_confidence, snapshot_from_hits


def _hit(score, q="Who pays return shipping?", a="Orders over $99 ship free; the buyer pays return shipping."):
    return {"question": q, "answer": a, "rerank_score": score,
            "section_path": "Support / Returns", "id": 1, "content_type": "faq"}


def test_empty_hits_zero_confidence():
    r = compute_evidence_confidence([])
    assert r.score == 0.0
    assert r.signals == {"top1_score": 0.0, "valid_count": 0, "margin": 0.0, "key_clause_hit": False}


def test_strong_evidence_scores_high():
    r = compute_evidence_confidence([_hit(0.95), _hit(0.40), _hit(0.35)])
    assert r.score > 0.7
    assert r.signals["top1_score"] == 0.95
    assert r.signals["margin"] == pytest.approx(0.55)
    assert r.signals["key_clause_hit"] is True


def test_weak_flat_evidence_scores_low():
    hits = [_hit(0.22, q="猫粮口味", a="三文鱼味与鸡肉味"),
            _hit(0.21, q="猫粮口味", a="三文鱼味与鸡肉味")]
    r = compute_evidence_confidence(hits)
    assert r.score < 0.4
    assert r.signals["valid_count"] == 0
    assert r.signals["key_clause_hit"] is False


def test_single_hit_margin_falls_back_to_top1():
    r = compute_evidence_confidence([_hit(0.8)])
    assert r.signals["margin"] == pytest.approx(0.8)


def test_score_monotonic_in_top1():
    low = compute_evidence_confidence([_hit(0.3), _hit(0.2)])
    high = compute_evidence_confidence([_hit(0.9), _hit(0.2)])
    assert high.score > low.score


def test_score_bounded_zero_one():
    r = compute_evidence_confidence([_hit(1.0), _hit(0.0)])
    assert 0.0 <= r.score <= 1.0


def test_snapshot_from_hits_top3_shape():
    hits = [_hit(0.9), _hit(0.8), _hit(0.7), _hit(0.6)]
    snap = snapshot_from_hits(hits)
    assert len(snap) == 3
    assert snap[0] == {"question": "Who pays return shipping?", "answer": "Orders over $99 ship free; the buyer pays return shipping.",
                       "rerank_score": 0.9, "section_path": "Support / Returns"}


def test_snapshot_empty_hits():
    assert snapshot_from_hits([]) == []
