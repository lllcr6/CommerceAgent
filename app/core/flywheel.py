import logging

from pydantic import BaseModel, Field

from app.core import llm
from app.core.llm import get_chat_model
from app.core.prompts import FLYWHEEL_NORMALIZE_PROMPT
from app.db import repository

logger = logging.getLogger(__name__)


class NormalizeResult(BaseModel):
    normalized_question: str = Field(description="Normalized FAQ-style question")
    matched_question_id: int | None = Field(default=None, description="Matched candidate ID, or null if none matches")
    ai_suggested_answer: str = Field(default="", description="Suggested answer for review")


def _chain():
    return FLYWHEEL_NORMALIZE_PROMPT | llm.structured(NormalizeResult)


async def normalize_and_match(raw_question: str, candidates: list[dict]) -> NormalizeResult:

    """Return the normalized question, matched candidate ID, and suggested answer from one model call."""
    cand_text = "\n".join(
        f"- id={c['id']}: {c['normalized_question']}" for c in candidates) or "(no candidates)"
    return await _chain().ainvoke({"raw_question": raw_question, "candidates": cand_text})


async def process_pending(limit: int = 50) -> dict:

    """Normalize unmatched questions, merge duplicate gaps, enqueue new reviews, and return batch statistics."""
    rows = await repository.fetch_unmatched_low_conf(limit)
    stats = {"processed": 0, "merged": 0, "created": 0, "skipped": 0}
    for row in rows:

        fetched = await repository.list_review_candidates(limit=201)
        truncated = len(fetched) > 200
        candidates = fetched[:200]
        try:
            r = await normalize_and_match(row.raw_question, candidates)
        except Exception:
            logger.warning("Question normalization failed: lcq=%s; skipping until the next batch", row.id, exc_info=True)
            stats["skipped"] += 1
            continue
        mid = r.matched_question_id
        if mid is not None:
            if not any(c["id"] == mid for c in candidates):
                logger.warning("Normalization returned an unknown candidate: id=%s lcq=%s; skipping until the next batch", mid, row.id)
                stats["skipped"] += 1
                continue
            await repository.increment_occurrence(mid)
            review_id = mid
            stats["merged"] += 1
        else:
            review_id = await repository.insert_review_item(
                r.normalized_question, r.ai_suggested_answer or None)
            stats["created"] += 1
        await repository.set_matched_review(row.id, review_id)
        stats["processed"] += 1
        logger.info("flywheel lcq=%s → review=%s(%s)%s", row.id, review_id,
                    "matched" if mid is not None else "created",
                    " [Candidates truncated to 200; deduplication coverage is incomplete]" if truncated else "")
    return stats
