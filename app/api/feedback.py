"""Record unresolved customer feedback with a best-effort evidence snapshot."""
import logging

from fastapi import APIRouter, Depends

from app.db import repository
from app.auth import customer
from app.access import conversation_access
from app.graph import runtime
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _same_question(a: str, b: str) -> bool:
    return "".join(a.split()) == "".join(b.split())


@router.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest, user=Depends(customer)) -> FeedbackResponse:
    await conversation_access(req.conversation_id, user)
    if req.rating == "up":
        logger.info("Positive feedback logged: conv=%s q=%r", req.conversation_id, req.question[:40])
        return FeedbackResponse(pooled=False)

    snapshot = None
    try:
        turn = await runtime.get_turn_snapshot(req.conversation_id)
        if turn["snapshot"] and _same_question(turn["question"], req.question):
            snapshot = turn["snapshot"]
    except Exception:
        logger.warning("Feedback snapshot lookup failed: conv=%s; recording the question without a snapshot", req.conversation_id, exc_info=True)

    await repository.insert_low_confidence(
        req.conversation_id, req.question, "user_feedback", "Customer reported an unresolved question",
        retrieved_chunks=snapshot,
    )
    logger.info("Negative feedback recorded: conv=%s snapshot=%s", req.conversation_id,
                "Available" if snapshot else "None")
    return FeedbackResponse(pooled=True)
