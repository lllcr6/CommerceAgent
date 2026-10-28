"""Generate append-only summary segments in the background while preserving immutable facts and history anchors."""
import asyncio
import logging
import time

from pydantic import BaseModel, Field

from app.config import settings
from app.core import budget, llm, memory
from app.core.llm import get_chat_model
from app.core.prompts import SUMMARY_PROMPT
from app.db import repository

logger = logging.getLogger(__name__)

_running: dict[int, asyncio.Task] = {}


class _Summary(BaseModel):
    summary: str = Field(description="Rolling summary of earlier conversation facts and requests")


async def summarize_dialog(old_summary: str, dialog: str) -> str:
    """Summarize a segment as structured output. Earlier summaries provide context and are never rewritten."""
    model = llm.structured(_Summary, slot="summary")
    r: _Summary = await (SUMMARY_PROMPT | model).ainvoke(
        {"old_summary": old_summary or "(none)", "dialog": dialog})
    return (r.summary or "").strip()


async def run_summary(conversation_id: int) -> None:
    """Append a summary segment and atomically advance its database anchor."""
    t0 = time.monotonic()
    conv = await repository.get_conversation(conversation_id)
    if conv is None:
        return
    msgs = await repository.list_dialog_messages(conversation_id)
    old_upto = conv.summary_upto_msg_id or 0


    boundary = conv.layer1_from_msg_id or 0
    if boundary <= old_upto:
        logger.info("Summary skipped: conv=%s layer2 is empty (boundary=%s upto=%s)",
                    conversation_id, boundary, old_upto)
        return
    seg = [m for m in msgs if old_upto < m.id <= boundary]
    dialog = "\n".join(
        f"{"Customer" if m.role == 'user' else "Support"}:{m.content}" for m in seg if m.content)
    logger.info("summary start conv=%s msgs=%s upto %s->%s",
                conversation_id, len(seg), old_upto, boundary)
    summary = await summarize_dialog(conv.summary or "", dialog)
    if not summary:
        raise ValueError("Summary is empty; skipping update")
    n = await repository.append_summary_segment(
        conversation_id, from_msg_id=old_upto + 1, upto_msg_id=boundary, content=summary)
    logger.info("Summary complete: conv=%s segment=%s upto=%s length=%s elapsed=%.0fms",
                conversation_id, n, boundary, len(summary), (time.monotonic() - t0) * 1000)


async def _should_summarize(conversation_id: int, conv) -> bool:

    """Trigger a summary only when compressed history exceeds its token budget; message count alone does not trigger compression."""
    upto = conv.summary_upto_msg_id or 0
    layer1_from = conv.layer1_from_msg_id or 0
    if layer1_from <= upto:
        return False
    msgs = await repository.list_dialog_messages(conversation_id)
    layer2_tok = memory.chars_to_tokens(
        sum(len(m.content or "") for m in msgs if upto < m.id <= layer1_from))
    l2_budget = int(budget.compute().sliding * (1 - settings.layer1_ratio))
    if layer2_tok <= l2_budget:
        return False
    logger.info("Summary triggered: conv=%s layer2_tokens~%s exceeds budget=%s",
                conversation_id, layer2_tok, l2_budget)
    return True


async def maybe_schedule_summary(conversation_id: int) -> None:
    """Schedule at most one background summary per conversation after a turn."""
    try:
        if conversation_id in _running:
            return
        conv = await repository.get_conversation(conversation_id)
        if conv is None:
            return
        if not await _should_summarize(conversation_id, conv):
            return

        if conversation_id in _running:
            return
        task = asyncio.create_task(run_summary(conversation_id))
        _running[conversation_id] = task

        def _done(t: asyncio.Task) -> None:
            if _running.get(conversation_id) is t:
                _running.pop(conversation_id, None)
            if not t.cancelled() and t.exception() is not None:
                logger.error("summary failed conv=%s", conversation_id, exc_info=t.exception())

        task.add_done_callback(_done)
    except Exception:
        logger.exception("summary trigger check failed conv=%s", conversation_id)
