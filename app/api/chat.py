import json
import logging
from collections.abc import AsyncIterator

from fastapi import Depends, APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.service_errors import KnowledgeServiceError
from app.core import generations
from app.auth import customer
from app.access import conversation_access
from app.graph import runtime
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_error(message: str) -> AsyncIterator[str]:
    yield "event: error\n"
    yield _sse({"message": message})


@router.post("/api/chat")
async def chat(req: ChatRequest, user=Depends(customer), benchmark_request: str | None = Header(default=None, alias='X-Benchmark-Request')):
    if benchmark_request is not None:
        import re
        if not user.id.startswith('bench_') or not re.fullmatch('[a-f0-9]{32}', benchmark_request) or req.conversation_id is None:
            raise HTTPException(400, 'Benchmark request IDs require a synthetic account and an existing conversation.')
    req.user_id = user.id
    if req.order_id:
        from app.business_store import owns_order
        if not await owns_order(user.id, req.order_id):
            raise HTTPException(404, "Order not found.")
        req.message = f"[Order: {req.order_id}]\n{req.message}"
    if req.conversation_id is not None:
        conv = await conversation_access(req.conversation_id, user, write=True)
        if conv.user_id != user.id:
            raise HTTPException(403, "Only the conversation owner can start an AI reply.")
        if conv.status == "handed_off":
            previous = await generations.snapshot(req.conversation_id) if benchmark_request else None
            if not previous or previous['run_id'] != benchmark_request:
                raise HTTPException(409, "Use the human-support message area while a support agent is handling this conversation.")
    if req.conversation_id is None:
        from app.db import repository
        try:
            req.conversation_id = await repository.create_conversation(user.id)
        except SQLAlchemyError:
            raise HTTPException(503, "The database is temporarily unavailable. Please try again shortly.")

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for ev in runtime.stream_turn(req.user_id, req.message, req.conversation_id):
                if ev["type"] == "session":
                    yield _sse({"event": "session", "conversation_id": ev["conversation_id"]})
                elif ev["type"] == "tool":
                    yield _sse({"event": "tool", "name": ev["name"]})
                elif ev["type"] == "delta":
                    yield _sse({"delta": ev["text"]})
                elif ev["type"] == "citations":
                    yield _sse({"event": "citations", "items": ev["items"]})
                elif ev["type"] == "interrupt":

                    yield _sse({"event": "interrupt",
                                **{k: v for k, v in ev.items() if k != "type"}})
                elif ev["type"] == "actions":
                    yield _sse({"event": "actions", "items": ev["items"]})
                elif ev["type"] == "done":
                    yield _sse({"event": "done", "conversation_id": ev["conversation_id"]})
        except runtime.ConversationNotFound:
            for f in _sse_error("Conversation not found."):
                yield f
            return
        except SQLAlchemyError:
            logger.exception("Database error: user_id=%s", req.user_id)
            for f in _sse_error("The database is temporarily unavailable. Please try again shortly."):
                yield f
            return
        except KnowledgeServiceError as exc:
            logger.exception("Knowledge service failed: component=%s", exc.component)
            yield _sse({"event": "actions", "items": [{"type": "transfer_human"}], "conversation_id": req.conversation_id})
            for frame in _sse_error(str(exc)):
                yield frame
            return
        except Exception:
            logger.exception("Graph execution failed: user_id=%s", req.user_id)
            yield _sse({"event": "actions", "items": [{"type": "transfer_human"}], "conversation_id": req.conversation_id})
            for f in _sse_error("The model is unavailable after retries. You can contact support."):
                yield f
            return
        yield "data: [DONE]\n\n"

    run_id = await generations.start(req.conversation_id, user.id, event_stream,
                                     **({'request_id':benchmark_request} if benchmark_request else {}))
    return StreamingResponse(generations.stream(req.conversation_id, run_id), media_type="text/event-stream",
                             headers={"X-Conversation-Id": str(req.conversation_id), "X-Generation-Id": run_id,
                                      "Cache-Control": "no-cache"})


@router.post('/api/benchmark/conversations')
async def benchmark_conversation(user=Depends(customer)):
    if not user.id.startswith('bench_'):
        raise HTTPException(403, 'Synthetic benchmark account required.')
    from app.db import repository
    return {'conversation_id': await repository.create_conversation(user.id)}


@router.get("/api/conversations/{cid}/generation")
async def generation_status(cid: int, user=Depends(customer)):
    conv = await conversation_access(cid, user)
    if conv.user_id != user.id:
        raise HTTPException(403, "Only the conversation owner can recover generated replies")
    snap = await generations.snapshot(cid)
    if not snap:
        return {"state": "idle", "run_id": None}
    return {key: value for key, value in snap.items() if key != "frames"}


@router.get("/api/conversations/{cid}/generation/events")
async def generation_events(cid: int, run_id: str, user=Depends(customer)):
    conv = await conversation_access(cid, user)
    if conv.user_id != user.id:
        raise HTTPException(403, "Only the conversation owner can recover generated replies")
    snap = await generations.snapshot(cid)
    if not snap or snap["run_id"] != run_id:
        raise HTTPException(404, "Generation record not found")
    return StreamingResponse(generations.stream(cid, run_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Conversation-Id": str(cid), "X-Generation-Id": run_id})
