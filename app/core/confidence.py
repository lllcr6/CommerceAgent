"""Score retrieved evidence using top score, valid-hit count, score margin, and key-clause matches without additional model calls. Calibration selects the threshold."""
from dataclasses import dataclass

from app.kb.documents import KEY_TERMS, has_key_terms

VALID_SCORE_FLOOR = 0.3
VALID_COUNT_CAP = 3
W_TOP1, W_VALID, W_MARGIN, W_KEY = 0.5, 0.2, 0.2, 0.1


@dataclass
class EvidenceConfidence:
    score: float
    signals: dict


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_evidence_confidence(hits: list[dict]) -> EvidenceConfidence:
    if not hits:
        return EvidenceConfidence(0.0, {"top1_score": 0.0, "valid_count": 0,
                                        "margin": 0.0, "key_clause_hit": False})
    scores = [float(h.get("rerank_score", 0.0)) for h in hits]
    top1 = scores[0]
    margin = top1 - scores[1] if len(scores) > 1 else top1
    valid_count = sum(1 for s in scores if s >= VALID_SCORE_FLOOR)
    key_hit = any(
        has_key_terms(f"{h.get('question', '')} {h.get('answer', '')}")
        for h in hits[:3]
    )
    score = (W_TOP1 * _clip01(top1)
             + W_VALID * min(valid_count, VALID_COUNT_CAP) / VALID_COUNT_CAP
             + W_MARGIN * _clip01(margin)
             + W_KEY * (1.0 if key_hit else 0.0))
    return EvidenceConfidence(round(_clip01(score), 4),
                              {"top1_score": top1, "valid_count": valid_count,
                               "margin": round(margin, 4), "key_clause_hit": key_hit})


def snapshot_from_hits(hits: list[dict], top_n: int = 3) -> list[dict]:
    """Capture the top retrieved passages and scores for human review."""
    return [{"question": h.get("question", ""), "answer": h.get("answer", ""),
             "rerank_score": float(h.get("rerank_score", 0.0)),
             "section_path": h.get("section_path", "")}
            for h in hits[:top_n]]
