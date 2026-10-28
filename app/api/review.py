"""Human approval and rejection of knowledge gaps. Publish approved evidence before finalizing review status."""
import logging

from fastapi import APIRouter, HTTPException

from app.db import repository
from app.kb import dualwrite
from app.kb.documents import Chunk, is_key
from app.schemas.review import ApproveRequest

logger = logging.getLogger(__name__)
router = APIRouter()


async def _write_chunks(chunks: list[Chunk]) -> list[int]:
    return await dualwrite.write_pending(chunks)


async def _vectorize() -> int:
    return await dualwrite.vectorize_pending()


def _item_out(r) -> dict:
    return {"id": r.id, "normalized_question": r.normalized_question,
            "ai_suggested_answer": r.ai_suggested_answer,
            "occurrence_count": r.occurrence_count, "review_status": r.review_status,
            "created_at": r.created_at.isoformat() if r.created_at else None}


@router.get("/api/review/queue")
async def review_queue(status: str | None = None) -> dict:

    """Prioritize knowledge gaps by the number of repeated customer questions."""
    rows = await repository.list_review_queue(status)
    return {"items": [_item_out(r) for r in rows]}


@router.get("/api/review/{review_id}")
async def review_detail(review_id: int) -> dict:

    """Return original questions and evidence snapshots so reviewers can distinguish missing knowledge from failed retrieval."""
    detail = await repository.get_review_detail(review_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Knowledge gap not found.")
    item, raws = detail
    out = _item_out(item)
    out["approved_answer"] = item.approved_answer
    out["raws"] = [{"raw_question": r.raw_question, "source": r.source, "reason": r.reason,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "retrieved_chunks": r.retrieved_chunks}
                   for r in raws]
    return out


@router.post("/api/review/{review_id}/approve")
async def approve(review_id: int, req: ApproveRequest) -> dict:
    detail = await repository.get_review_detail(review_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Knowledge gap not found.")
    item, _ = detail
    if item.review_status != "pending":
        raise HTTPException(status_code=409, detail="Only pending items can be reviewed.")

    chunk = Chunk(
        category="Reviewed knowledge", questions=item.normalized_question, answer=req.approved_answer,
        section_path=f"Reviewed knowledge / {item.normalized_question}", content_type="faq",
        is_key_clause=is_key(item.normalized_question, req.approved_answer),
    )
    chunk_ids: list[int] = []
    try:
        chunk_ids = await _write_chunks([chunk])
        await _vectorize()
    except Exception:
        logger.exception("Knowledge publishing failed: review=%s; review remains pending and can be retried", review_id)
        if chunk_ids:


            try:
                await repository.delete_knowledge_chunks(chunk_ids)
            except Exception:
                logger.exception("Pending chunk rollback failed: ids=%s; manual cleanup required", chunk_ids)
        raise HTTPException(status_code=502, detail="Knowledge write failed. Check the embedding provider and Milvus, then retry; review status is unchanged.")

    if not await repository.update_review_status(review_id, "approved", approved_answer=req.approved_answer):

        logger.warning("Review status update lost a concurrent race: review=%s; knowledge chunks already written=%s", review_id, chunk_ids)
        raise HTTPException(status_code=409, detail="Review status changed concurrently. Knowledge was written; verify the result before retrying.")
    logger.info("Review approved: review=%s → knowledge_chunks=%s; indexed for subsequent queries", review_id, chunk_ids)
    return {"ok": True, "chunk_ids": chunk_ids}


@router.post("/api/review/{review_id}/reject")
async def reject(review_id: int) -> dict:
    if not await repository.update_review_status(review_id, "rejected"):
        detail = await repository.get_review_detail(review_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Knowledge gap not found.")
        raise HTTPException(status_code=409, detail="Only pending reviews can be rejected.")
    return {"ok": True}
