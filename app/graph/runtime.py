import logging
from collections.abc import AsyncIterator
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.config import settings
from app.core import summarizer
from app.core.observability import attach_observability
from app.config import settings
from app.core import budget, memory
from app.db import repository
from app.graph.build import build_graph

logger = logging.getLogger(__name__)


ANSWER_NODES = {"main_agent"}

DETERMINISTIC_ANSWER_NODES = {"script_reply", "complaint_reply", "fallback_reply", "agent_tools"}

CITATION_NODES = {"retrieve_knowledge", "retrieve_policy"}

_graph = None
_cm = None


class ConversationNotFound(Exception):
    pass


async def init_graph() -> None:
    """Open the persistent checkpointer and compile the graph during startup."""
    global _graph, _cm
    Path(settings.checkpointer_db_path).parent.mkdir(parents=True, exist_ok=True)
    _cm = AsyncSqliteSaver.from_conn_string(settings.checkpointer_db_path)
    checkpointer = await _cm.__aenter__()
    await checkpointer.setup()

    _graph = attach_observability(build_graph(checkpointer=checkpointer))
    logger.info("Graph compiled: checkpointer=%s", settings.checkpointer_db_path)


async def close_graph() -> None:
    global _graph, _cm
    if _cm is not None:
        await _cm.__aexit__(None, None, None)
        _cm = None
    _graph = None


def get_graph():
    if _graph is None:
        raise RuntimeError("Graph is uninitialized; call init_graph() in the FastAPI lifespan")
    return _graph


async def get_turn_snapshot(conversation_id: int) -> dict:
    """Read the latest question and evidence snapshot. The caller must match the feedback question before using the snapshot."""
    config = {"configurable": {"thread_id": str(conversation_id)}}
    st = await get_graph().aget_state(config)
    values = getattr(st, "values", None) or {}
    question = ""
    for m in reversed(values.get("messages", [])):
        if getattr(m, "type", "") == "human":
            question = m.content if isinstance(m.content, str) else ""
            break
    return {"question": question, "snapshot": values.get("retrieved_snapshot") or []}


def dedup_actions(actions: list) -> list:
    """Keep the first suggested action of each type across ReAct steps."""
    seen = set()
    out = []
    for action in actions:
        t = action.get("type")
        if t in seen:
            continue
        seen.add(t)
        out.append(action)
    return out


async def _ensure_conversation(user_id: str,
                               conversation_id: int | None) -> tuple[int, str, int, int]:
    """Load conversation ID, summary, and both history anchors in one read."""
    if conversation_id is None:
        return await repository.create_conversation(user_id), "", 0, 0
    conv = await repository.get_conversation(conversation_id)
    if conv is None or conv.user_id != user_id:
        raise ConversationNotFound(conversation_id)
    if conv.status != "active":
        from fastapi import HTTPException
        raise HTTPException(409, "This conversation is closed or being handled by human support")
    return (conversation_id, conv.summary or "",
            conv.summary_upto_msg_id or 0, conv.layer1_from_msg_id or 0)


def _graph_input(user_id: str, message: str, cid: int, msg_id: int,
                 summary: str, summary_upto: int, layer1_from: int = 0) -> dict:


    return {"messages": [HumanMessage(message, id=f"db-{msg_id}")], "user_id": user_id,
            "conversation_id": cid, "steps": 0, "tokens_used": 0,
            "human_requested": False, "answer": "", "suggested_actions": [], "evidence": "",
            "evidence_strong": False, "citations": [],
            "evidence_confidence": 0.0, "fallback_source": "", "retrieved_snapshot": [],
            "resolved_query": "", "intent_confidence": 0.0,
            "order_id": "", "order_data": {},
            "summary": summary, "summary_upto_msg_id": summary_upto,
            "layer1_from_msg_id": layer1_from,
            "trace": None}


def _interrupt_payload(state: dict):
    """Return the complete typed interrupt payload, or None when absent."""
    intr = state.get("__interrupt__")
    if not intr:
        return None
    return intr[0].value


async def _final_state(cid: int) -> dict:
    """Load the checkpointed final state after streaming."""
    snap = await get_graph().aget_state({"configurable": {"thread_id": str(cid)}})
    return snap.values if snap else {}


async def settle_layers(cid: int, state: dict | None,
                        summary_upto: int, layer1_from: int) -> None:
    """Demote history only when over budget, preserving stable prefixes between changes. Settlement failure never blocks an already generated reply."""
    try:
        if state is None:
            state = await _final_state(cid)
        msgs = (state or {}).get("messages") or []
        if not msgs:
            return
        l1_budget = int(budget.compute().sliding * settings.layer1_ratio)
        _, layer1_tok = memory.layer_tokens(msgs, summary_upto, layer1_from)
        if layer1_tok <= l1_budget:
            return
        new_from = memory.next_layer1_from(msgs, summary_upto, l1_budget)
        if new_from > layer1_from:
            await repository.update_layer1_from(cid, new_from)
            logger.info("History layer demoted: conv=%s %s→%s (layer1=%s exceeds budget=%s)",
                        cid, layer1_from, new_from, layer1_tok, l1_budget)
    except Exception:
        logger.exception("History layer update failed: conv=%s; reply is unaffected", cid)


async def _trace_config(cid):
    from app.usage_store import UsageCallback
    conv = await repository.get_conversation(cid)
    user_id = getattr(conv, 'user_id', '')
    callback = UsageCallback(cid, user_id)
    synthetic = str(user_id).startswith('bench_')
    return {'configurable': {'thread_id': str(cid)}, 'callbacks': [callback],
            'tags': ['synthetic:agent-benchmark'] if synthetic else ['traffic:customer'],
            'metadata': {'langfuse_session_id': str(cid), 'usage_turn_id': callback.turn_id,
                         'traffic_type': 'synthetic' if synthetic else 'customer'}}


async def _run_turn(user_id, message, conversation_id) -> dict:
    """Persist the customer message and invoke the graph, retaining any interrupt payload."""
    cid, summary, upto, layer1 = await _ensure_conversation(user_id, conversation_id)
    msg_id = await repository.append_message(cid, "user", content=message)

    config = await _trace_config(cid)
    final = await get_graph().ainvoke(
        _graph_input(user_id, message, cid, msg_id, summary, upto, layer1), config)
    await settle_layers(cid, final, upto, layer1)
    await summarizer.maybe_schedule_summary(cid)
    return {"conversation_id": cid, "state": final, "interrupt": _interrupt_payload(final)}


async def _resume_turn(conversation_id: int, resume_value) -> dict:
    """Resume the graph until its next interrupt or completion."""
    if await repository.get_conversation(conversation_id) is None:
        raise ConversationNotFound(conversation_id)
    config = await _trace_config(conversation_id)
    final = await get_graph().ainvoke(Command(resume=resume_value), config)
    await summarizer.maybe_schedule_summary(conversation_id)
    return {"conversation_id": conversation_id, "state": final,
            "interrupt": _interrupt_payload(final)}


async def _stream_events(cid: int, stream_source) -> AsyncIterator[dict]:
    """Convert multi-mode graph output to API events; interrupts end the stream until explicit resume."""
    config = await _trace_config(cid)
    actions: list = []
    async for mode, chunk in get_graph().astream(
        stream_source, config, stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            msg, meta = chunk
            if meta.get("langgraph_node") in ANSWER_NODES:
                text = msg.content if isinstance(msg.content, str) else ""
                if text:
                    yield {"type": "delta", "text": text}
        elif mode == "updates":
            if "__interrupt__" in chunk:
                payload = chunk["__interrupt__"][0].value


                ev = {"type": "interrupt", "kind": payload.get("type", ""), "conversation_id": cid}
                for k in ("orders", "preview"):
                    if payload.get(k) is not None:
                        ev[k] = payload[k]
                yield ev
                return
            for node, upd in chunk.items():
                if not isinstance(upd, dict):
                    continue
                if node in DETERMINISTIC_ANSWER_NODES and upd.get("answer"):
                    yield {"type": "delta", "text": upd["answer"]}
                if node in CITATION_NODES and upd.get("citations"):
                    yield {"type": "citations", "items": upd["citations"]}
                if node == "agent_tools":
                    for m in upd.get("messages", []):
                        name = getattr(m, "name", None)


                        if name and name != "submit_refund":
                            yield {"type": "tool", "name": name}
                if upd.get("suggested_actions"):
                    actions.extend(upd["suggested_actions"])
    if actions:
        yield {"type": "actions", "items": dedup_actions(actions)}
    yield {"type": "done", "conversation_id": cid}


async def _stream_turn(user_id, message, conversation_id) -> AsyncIterator[dict]:
    """Persist a customer message and stream graph events."""
    cid, summary, upto, layer1 = await _ensure_conversation(user_id, conversation_id)
    msg_id = await repository.append_message(cid, "user", content=message)
    async for ev in _stream_events(
            cid, _graph_input(user_id, message, cid, msg_id, summary, upto, layer1)):
        yield ev
    await settle_layers(cid, None, upto, layer1)
    await summarizer.maybe_schedule_summary(cid)


async def _stream_resume(conversation_id: int, resume_value) -> AsyncIterator[dict]:
    """Resume an interrupted conversation using the same event schema."""
    if await repository.get_conversation(conversation_id) is None:
        raise ConversationNotFound(conversation_id)
    async for ev in _stream_events(conversation_id, Command(resume=resume_value)):
        yield ev
    await summarizer.maybe_schedule_summary(conversation_id)


async def _active(cid):
    from fastapi import HTTPException
    conv = await repository.get_conversation(cid)
    if conv is None:
        raise ConversationNotFound(cid)
    if conv.status != "active":
        raise HTTPException(409, "This conversation is closed or being handled by human support")

async def run_turn(user_id, message, conversation_id):
    from app.api.service import conversation_lock
    cid = conversation_id or await repository.create_conversation(user_id)
    async with conversation_lock(cid):
        await _active(cid)
        return await _run_turn(user_id, message, cid)

async def stream_turn(user_id, message, conversation_id):
    from app.api.service import conversation_lock
    cid = conversation_id or await repository.create_conversation(user_id)
    async with conversation_lock(cid):
        await _active(cid)
        # Persist and announce the conversation before any model call can fail.
        yield {"type": "session", "conversation_id": cid}
        async for ev in _stream_turn(user_id, message, cid):
            yield ev

async def resume_turn(conversation_id, resume_value):
    from app.api.service import conversation_lock
    async with conversation_lock(conversation_id):
        await _active(conversation_id)
        return await _resume_turn(conversation_id, resume_value)

async def stream_resume(conversation_id, resume_value):
    from app.api.service import conversation_lock
    async with conversation_lock(conversation_id):
        await _active(conversation_id)
        async for ev in _stream_resume(conversation_id, resume_value):
            yield ev
