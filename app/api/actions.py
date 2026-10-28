import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from app.db import repository
from app.auth import customer
from app.access import conversation_access
from app.graph import runtime
from app.core import generations
from app.schemas.actions import (
    CreateRefundRequest,
    CreateRefundResponse,
    CreateTicketRequest,
    CreateTicketResponse,
    ResumeRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/actions/create-ticket", response_model=CreateTicketResponse)
async def create_ticket_action(req: CreateTicketRequest, user=Depends(customer)) -> CreateTicketResponse:
    conv = await conversation_access(req.conversation_id, user, write=True)

    try:
        ticket_no = await repository.create_ticket(
            req.conversation_id, req.description, req.ticket_type, **({"order_id": req.order_id} if req.order_id else {}))
    except SQLAlchemyError:
        logger.exception("Ticket creation failed: conv=%s", req.conversation_id)
        raise HTTPException(status_code=503, detail="The ticket service is temporarily unavailable. Please try again shortly.")
    return CreateTicketResponse(ticket_no=ticket_no)


@router.post("/api/actions/create-refund", response_model=CreateRefundResponse)
async def create_refund_action(req: CreateRefundRequest, user=Depends(customer)) -> CreateRefundResponse:
    conv = await conversation_access(req.conversation_id, user, write=True)
    from app.business_store import owns_order
    if not await owns_order(conv.user_id, req.order_id):
        raise HTTPException(404, "Order not found.")
    desc = f"Refund request: order={req.order_id} reason={req.reason.replace('_', ' ')}"
    try:
        ticket_no = await repository.create_ticket(req.conversation_id, desc, "refund", order_id=req.order_id)
    except SQLAlchemyError:
        logger.exception("Refund ticket creation failed: conv=%s", req.conversation_id)
        raise HTTPException(status_code=503, detail="The refund-request service is temporarily unavailable. Please try again shortly.")
    return CreateRefundResponse(ticket_no=ticket_no)


@router.post("/api/actions/resume")
async def resume_action(req: ResumeRequest, user=Depends(customer)):
    conv = await conversation_access(req.conversation_id, user, write=True)
    if conv.user_id != user.id or conv.status != "active":
        raise HTTPException(409, "This conversation cannot be continued.")
    if req.order_id is None and req.confirmed is None:
        raise HTTPException(status_code=400, detail="Provide order_id or confirmed.")
    resume_value = req.order_id if req.order_id is not None else {"confirmed": bool(req.confirmed)}

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for ev in runtime.stream_resume(req.conversation_id, resume_value):
                if ev["type"] == "tool":
                    yield _sse({"event": "tool", "name": ev["name"]})
                elif ev["type"] == "delta":
                    yield _sse({"delta": ev["text"]})
                elif ev["type"] == "citations":
                    yield _sse({"event": "citations", "items": ev["items"]})
                elif ev["type"] == "actions":
                    yield _sse({"event": "actions", "items": ev["items"]})
                elif ev["type"] == "interrupt":
                    yield _sse({"event": "interrupt",
                                **{k: v for k, v in ev.items() if k != "type"}})
                elif ev["type"] == "done":
                    yield _sse({"event": "done", "conversation_id": ev["conversation_id"]})
        except runtime.ConversationNotFound:
            yield "event: error\n"
            yield _sse({"message": "Conversation not found."})
            return
        except Exception:
            logger.exception("Could not resume conv=%s", req.conversation_id)
            yield "event: error\n"
            yield _sse({"message": "The model service is temporarily unavailable. You can contact support.", "conversation_id": req.conversation_id, "suggested_actions": [{"type": "transfer_human"}]})
            return
        yield "data: [DONE]\n\n"

    run_id = await generations.start(req.conversation_id, user.id, event_stream, resume=True)
    return StreamingResponse(generations.stream(req.conversation_id, run_id), media_type="text/event-stream",
                             headers={"X-Conversation-Id": str(req.conversation_id), "X-Generation-Id": run_id,
                                      "Cache-Control": "no-cache"})
