import json
import logging
import re
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import interrupt

from app.config import settings
from app.core import coref
from app.core import intent as intent_mod
from app.core import memory
from app.core import query_understanding, retrieval, selfcheck
from app.core.confidence import compute_evidence_confidence, snapshot_from_hits
from app.core.llm import get_chat_model
from app.core.observability import tag_intent
from app.core.prompts import (
    AGENT_SYSTEM, COMPLAINT_REPLY_TEXT, FALLBACK_REPLY_TEXT,
    REFUND_JUDGE_HINT, SCRIPT_REPLY_CHITCHAT, SCRIPT_REPLY_OTHER,
)
from app.db import repository
from app.graph.routing import INTENT_TO_ROUTE
from app.tools import business, engine, registry

logger = logging.getLogger(__name__)

COMPLAINT_REPLY = COMPLAINT_REPLY_TEXT
FALLBACK_REPLY = FALLBACK_REPLY_TEXT


def _user_text(state) -> str:
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            return m.content or ""
    return ""


def _history_text(state, max_turns: int = 6) -> str:
    """Combine the summary and anchored recent history, excluding the current customer message."""
    msgs = memory.build_window(state.get("messages", []),
                               state.get("summary_upto_msg_id") or 0,
                               state.get("layer1_from_msg_id") or 0)
    prior = msgs[:-1] if msgs else []
    lines = []
    for m in prior[-max_turns:]:
        role = "Customer" if isinstance(m, HumanMessage) else "Support"
        text = m.content if isinstance(m.content, str) else ""
        if text:
            lines.append(f"{role}:{text}")
    body = "\n".join(lines)
    head = memory.summary_line(state.get("summary"))
    return f"{head}\n{body}".strip() if head else body


_ORDER_RE = re.compile(r"(?<![a-zA-Z0-9_.-])([a-zA-Z0-9_.-]+-\d{4}|\d{4,})(?![a-zA-Z0-9_.-])")


def _extract_order_id(text: str) -> str | None:
    m = _ORDER_RE.search(text or "")
    return m.group(1) if m else None


async def fetch_order(state) -> dict:
    """Resolve and verify order ownership before the refund workflow. Interrupt for missing or foreign orders; perform only reads before interrupt because resume reruns the node."""
    uid = state.get("user_id", "")
    oid = state.get("order_id") or _extract_order_id(
        state.get("resolved_query") or _user_text(state))
    while not await business.owns_order(uid, str(oid or "")):
        orders = await business.list_user_orders(uid)
        oid = interrupt({"type": "select_order", "orders": orders})
    data = await business.order_snapshot(oid)
    return {"order_id": oid, "order_data": data,
            "trace": {"fetch_order": {"order_id": oid}}}


async def retrieve_policy(state) -> dict:
    """Expand the refund query, retrieve evidence, deduplicate by chunk ID using the highest score, and provide numbered policy passages."""
    base = state.get("resolved_query") or _user_text(state)
    od = state.get("order_data") or {}
    seed = f"{base} {od.get('status', '')}".strip()
    queries = await query_understanding.expand_queries(seed)

    merged: dict = {}
    for q in queries:
        for h in await retrieval.search_knowledge(q, strategy="hybrid_rerank", bm25_text=q):
            cur = merged.get(h["id"])
            if cur is None or h["rerank_score"] > cur["rerank_score"]:
                merged[h["id"]] = h
    ranked = sorted(merged.values(), key=lambda h: h["rerank_score"], reverse=True)
    arranged = retrieval.arrange_head_tail(ranked)
    citations = [
        {"n": i + 1, "id": h["id"], "section_path": h["section_path"],
         "question": h["question"], "answer": h["answer"], "content_type": h["content_type"]}
        for i, h in enumerate(arranged)
    ]
    evidence = "\n".join(f"[{c['n']}] {c['question']}: {c['answer']}" for c in citations)
    return {"evidence": evidence, "citations": citations,
            "trace": {"retrieve_policy": {"queries": queries, "hits": len(ranked)}}}


async def script_reply(state) -> dict:
    """Return the deterministic greeting or clarification response for the routed intent."""
    text = SCRIPT_REPLY_OTHER if state.get("intent", "") == "other" else SCRIPT_REPLY_CHITCHAT
    return {"answer": text, "trace": {"route": "fallback_script"}}


async def complaint_reply(state) -> dict:
    """Offer empathy plus optional human support and ticket actions."""
    actions = [
        {"type": "transfer_human"},
        {"type": "create_ticket",
         "draft": {"description": _user_text(state), "ticket_type": "complaint"}},
    ]
    return {"answer": COMPLAINT_REPLY, "suggested_actions": actions,
            "trace": {"route": "complaint"}}


async def fallback_reply(state) -> dict:
    """Return the unsupported-evidence response, offer human support, and record the question with its evidence snapshot for review."""
    source = state.get("fallback_source") or "retrieval_low_conf"
    signals = state.get("trace", {}).get("confidence_signals") or {}
    reason = (f"evidence_confidence={state.get('evidence_confidence', 0.0):.3f} "
              f"signals={json.dumps(signals, ensure_ascii=False)}")
    if source == "self_check":
        reason += f" self_check={state.get('trace', {}).get('self_check', '')}"


    walked_retrieval = bool(state.get("fallback_source"))
    snapshot = state.get("retrieved_snapshot") or ([] if walked_retrieval else None)
    await repository.insert_low_confidence(
        state.get("conversation_id"), _user_text(state), source, reason,
        retrieved_chunks=snapshot,
    )
    return {"answer": FALLBACK_REPLY,
            "suggested_actions": [{"type": "transfer_human"}],
            "trace": {"route": "fallback"}}


async def resolve_reference(state) -> dict:
    """Resolve references and normalize the query once for intent classification and retrieval."""
    query = _user_text(state)
    history = _history_text(state)


    logger.info("History context: conv=%s (summary and sliding window for reference resolution and intent)\n%s",
                state.get("conversation_id"), history or "(no history)")
    resolved = await coref.resolve(query, history)
    mode = "rewrite" if resolved != query else "passthrough"
    return {"resolved_query": resolved, "trace": {"coref": mode}}


async def classify_intent(state) -> dict:
    """Classify the resolved query and record the route using the shared intent-to-route mapping."""
    query = state.get("resolved_query") or _user_text(state)
    r = await intent_mod.classify(query, _history_text(state))
    intent, conf = r["intent"], r["confidence"]
    route = INTENT_TO_ROUTE.get(intent, "business")
    tag_intent(intent, conf)
    return {"intent": intent, "intent_confidence": conf, "route": route,
            "trace": {"intent": intent, "intent_confidence": conf, "route": route}}


async def _knowledge_order_context(state) -> dict:
    """Read the mentioned order before the knowledge gate, using normal tool auth/audit.

    A generic policy question does not require selecting an order. A selected order
    is refreshed every turn; never carry old order facts into a new question.
    """
    raw = _user_text(state)
    resolved = state.get("resolved_query") or raw
    selected = re.search(r"(?:【咨询订单：|\[Order: ?)([^】\]\s]+)[】\]]", raw)
    oid = None
    if selected:
        oid = selected.group(1)
    elif "订单" in resolved or re.search(r"\border\b", resolved, re.I):
        oid = _extract_order_id(resolved)
    if not oid or not state.get("user_id"):
        return {}
    from app.tools.builtin.orders import query_order
    spec = registry.spec_from_langchain_tool(query_order, source="builtin", inject_user_id=True)
    run = await engine.execute_tool_call(
        {"id": "knowledge-order-" + uuid.uuid4().hex, "name": "query_order", "args": {"order_id": oid}},
        state.get("conversation_id"), {"query_order": spec}, user_id=state["user_id"])
    data = {}
    if run.ok:
        try:
            data = json.loads(run.tool_message.content)
        except (ValueError, TypeError):
            pass
    if not isinstance(data, dict) or data.get("error") or data.get("order_id") != oid:
        data = {"error": "I could not verify that order. Please check the order number."}
    return {"order_id": oid, "order_data": data,
            "trace": {"knowledge_order": {"tool": "query_order", "available": not bool(data.get("error"))}}}


async def retrieve_knowledge(state) -> dict:
    """Always retrieve policy evidence before generation, score confidence, and preserve the top passages for feedback and review."""
    context = await _knowledge_order_context(state)
    query_raw = state.get("resolved_query") or _user_text(state)
    order = context.get("order_data", {})
    # Order IDs are identifiers, not policy keywords. Use verified product facts
    # for retrieval and retain the original question for the sufficiency check.
    search_text = query_raw
    if order.get("product"):
        search_text = search_text.replace(context["order_id"], order["product"])
    u = await query_understanding.understand(search_text)
    query = u["standard"]
    bm25_text = query + (" " + " ".join(u["expanded"]) if u["expanded"] else "")

    hits = await retrieval.search_knowledge(
        query, strategy="hybrid_rerank", bm25_text=bm25_text)
    conf = compute_evidence_confidence(hits)
    base = {**context, "evidence_confidence": conf.score,
            "retrieved_snapshot": snapshot_from_hits(hits)}
    order_trace = context.get("trace", {})


    if conf.score < settings.evidence_confidence_threshold:
        return {**base, "evidence_strong": False, "fallback_source": "retrieval_low_conf",
                "trace": {**order_trace, "forced_rag": True, "evidence_confidence": conf.score,
                          "confidence_signals": conf.signals}}


    ev_texts = [f"{h['question']} {h['answer']}" for h in hits]
    if order:
        ev_texts.append("Verified order facts (not policy): " + json.dumps(order, ensure_ascii=False))
    chk = await selfcheck.check_sufficient(query_raw, ev_texts)
    if not chk["useful"]:
        return {**base, "evidence_strong": False, "fallback_source": "self_check",
                "trace": {**order_trace, "forced_rag": True, "evidence_confidence": conf.score,
                          "confidence_signals": conf.signals, "self_check": chk["reason"]}}

    arranged = retrieval.arrange_head_tail(hits)
    citations = [
        {"n": i + 1, "id": h["id"], "section_path": h["section_path"],
         "question": h["question"], "answer": h["answer"], "content_type": h["content_type"]}
        for i, h in enumerate(arranged)
    ]
    evidence = "\n".join(f"[{c['n']}] {c['question']}: {c['answer']}" for c in citations)
    return {**base, "evidence_strong": True, "evidence": evidence, "citations": citations,
            "trace": {**order_trace, "forced_rag": True, "evidence_confidence": conf.score,
                      "confidence_signals": conf.signals}}


async def confidence_check(state) -> dict:
    """Record the evidence gate decision; the following conditional edge applies it."""
    decision = "strong" if state.get("evidence_strong") else "weak"
    return {"trace": {"confidence": decision}}


_KNOWLEDGE_EVIDENCE_HINT = (
    "\n\n## Retrieved evidence for this turn\n"
    "Answer using these sources and cite material claims with [1], [2], etc. "
    "Do not call query_faq again; other tools may supply verified business facts. "
    "Copy model IDs exactly and retain policy conditions.\n"
)


def _turn_context(state) -> str:
    """Build this turn's evidence and verified order context in prompt order."""
    parts = []
    ss = memory.summary_system(state.get("summary"))
    if ss is not None:
        parts.append("\n\n" + ss.content)
    if state.get("evidence"):
        parts.append(_KNOWLEDGE_EVIDENCE_HINT + state["evidence"])
    if state.get("route") == "knowledge" and state.get("order_data"):
        parts.append(
            "\n\n## Current query_order result\n" + json.dumps(state["order_data"], ensure_ascii=False) +
            "\nUse these facts only for product and order state; cite numbered evidence for policy. "
            "Explain rules conditionally and ask about missing delivery, opening, or defect facts. "
            "Do not automatically request a refund or guess facts when lookup fails. "
            "Use other business tools only as needed.")
    if state.get("route") == "refund_flow":
        parts.append(REFUND_JUDGE_HINT + json.dumps(state.get("order_data", {}), ensure_ascii=False))
    return "".join(parts)


TURN_CTX_ID = "turn-ctx"


def _with_turn_context(window: list, turn_ctx: str) -> list:
    """Insert context after the latest customer message so later ReAct steps retain the earlier request prefix."""
    msg = HumanMessage(turn_ctx, id=TURN_CTX_ID)
    for i in range(len(window) - 1, -1, -1):
        if isinstance(window[i], HumanMessage):
            return [*window[:i + 1], msg, *window[i + 1:]]
    return [*window, msg]


def _agent_messages(state) -> list:
    """Build a single stable system message, anchored history, and customer-side summary/evidence context. Never mutate full state history."""
    window = memory.build_window(state.get("messages", []),
                                 state.get("summary_upto_msg_id") or 0,
                                 state.get("layer1_from_msg_id") or 0)
    turn_ctx = _turn_context(state)
    if turn_ctx:
        window = _with_turn_context(window, turn_ctx)
    return [SystemMessage(AGENT_SYSTEM), *window]


def _log_model_context(state, msgs) -> None:
    """Log the summary and abbreviated history actually sent to the model."""


    ctx_block = next((m for m in msgs if getattr(m, "id", None) == TURN_CTX_ID), None)
    window = [m for m in msgs
              if not isinstance(m, SystemMessage) and getattr(m, "id", None) != TURN_CTX_ID]
    lines = []
    for m in window:
        text = m.content if isinstance(m.content, str) else ""
        lines.append(f"  [{m.type}] {text[:40]!r}")
    logger.info(
        "Model context: conv=%s step=%s summary=%r window=%s messages turn_context=%s tokens~%s\n%s",
        state.get("conversation_id"), state.get("steps", 0),
        state.get("summary") or "(none)", len(window),
        f"{len(ctx_block.content)} characters" if ctx_block else "none",
        memory.count_tokens(msgs), "\n".join(lines),
    )


async def main_agent(state, config=None) -> dict:
    """Execute one tool-enabled reasoning step and accumulate step and token usage."""
    specs = await registry.get_all_specs()
    model = get_chat_model(streaming=True).bind_tools([s.tool for s in specs])
    msgs = _agent_messages(state)
    _log_model_context(state, msgs)
    ai: AIMessage = await model.ainvoke(msgs, config)
    usage = ai.usage_metadata or {}
    from langchain_core.utils.function_calling import convert_to_openai_tool
    used, usage_source = memory.request_usage(msgs, ai, tools=[convert_to_openai_tool(s.tool) for s in specs])


    cached = (usage.get("input_token_details") or {}).get("cache_read", 0)
    logger.info("agent_step conv=%s step=%s input=%s cache_read=%s total=%s",
                state.get("conversation_id"), state.get("steps", 0) + 1,
                usage.get("input_tokens", 0), cached, used)
    return {"messages": [ai],
            "steps": state.get("steps", 0) + 1,
            "tokens_used": state.get("tokens_used", 0) + used,
            "trace": {"token_usage_source": usage_source}}


async def agent_tools(state) -> dict:
    """Execute through the shared engine. Interrupt for ticket confirmation only after valid arguments; do no writes before confirmation. Refund submission opens the customer form."""
    last = state["messages"][-1]
    cid = state.get("conversation_id", 0)
    uid = state.get("user_id", "")
    specs = {s.name: s for s in await registry.get_all_specs()}


    ticket_calls = [tc for tc in last.tool_calls if tc["name"] == "create_ticket"]
    tspec = specs.get("create_ticket")
    decision = None
    if ticket_calls and tspec is not None \
            and engine.validate_args(tspec, dict(ticket_calls[0].get("args") or {})) is None:
        first_args = ticket_calls[0]["args"]
        decision = interrupt({"type": "confirm_ticket",
                              "preview": {"ticket_type": first_args.get("ticket_type", "question"),
                                          "description": first_args.get("description", "")}})

    tool_msgs = []
    actions = list(state.get("suggested_actions", []))
    human_requested = False
    not_owned = False
    for tc in last.tool_calls:
        if human_requested:
            tool_msgs.append(ToolMessage(content="Human support requested. Stop tool execution.", tool_call_id=tc["id"], name=tc["name"]))
            continue
        if tc["name"] == "request_human":
            run = await engine.execute_tool_call(tc, cid, specs, user_id=uid, confirmed=True)
            tool_msgs.append(run.tool_message)
            human_requested = run.ok and '"state"' in run.tool_message.content
        elif tc["name"] == "submit_refund":


            if not await business.owns_order(uid, str(tc["args"].get("order_id") or "")):
                not_owned = True
                tool_msgs.append(ToolMessage(
                    content="This order was not found for the customer; no refund was initiated. Explain this and ask them to select one of their listed orders. Do not call more tools.",
                    tool_call_id=tc["id"], name="submit_refund", status="error"))
                continue
            actions.append({"type": "refund_form",
                            "draft": {"order_id": tc["args"].get("order_id", ""),
                                      "reason": tc["args"].get("reason")}})
            tool_msgs.append(ToolMessage(
                content="A refund-request form is awaiting the customer. Explain that the request still needs confirmation and review, then stop. Do not claim refund approval or call more tools.",
                tool_call_id=tc["id"], name="submit_refund"))
        elif tc["name"] == "create_ticket" and decision is not None:
            if tc is ticket_calls[0]:


                if isinstance(decision, dict) and decision.get("confirmed"):
                    run = await engine.execute_tool_call(tc, cid, specs, confirmed=True,
                                                        user_id=uid)
                else:
                    run = await engine.execute_tool_call(
                        tc, cid, specs, confirmed=False, user_id=uid,
                        deny_note="The customer cancelled the ticket preview. No ticket was created. Do not retry unless explicitly requested.")
                tool_msgs.append(run.tool_message)
            else:
                tool_msgs.append(ToolMessage(content="Only one ticket request can be processed at a time. This call was ignored.",
                                             tool_call_id=tc["id"], name="create_ticket",
                                             status="error"))
        else:

            run = await engine.execute_tool_call(tc, cid, specs, user_id=uid)
            if tc["name"] == "query_order" and not await business.owns_order(
                    uid, str((tc.get("args") or {}).get("order_id") or "")):
                not_owned = True
            tool_msgs.append(run.tool_message)

    if not_owned:
        actions.append({"type": "select_order", "orders": await business.list_user_orders(uid)})
    out = {"messages": tool_msgs}
    if human_requested:
        out.update(human_requested=True, answer="You are in the human-support queue. An agent will join when available.")
    if actions:
        out["suggested_actions"] = actions
    return out


def resolve_answer(state) -> str:
    """Return the deterministic answer or the final assistant message."""
    if state.get("answer"):
        return state["answer"]
    for m in reversed(state.get("messages", [])):
        if isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, str):
                return content
            return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


async def log_node(state) -> dict:
    """Record intent, route, trace, and the persisted assistant reply."""
    logger.info(
        "turn conv=%s intent=%s route=%s resolved=%r trace=%s",
        state.get("conversation_id"), state.get("intent"), state.get("route"),
        state.get("resolved_query"), state.get("trace", {}),
    )
    answer = resolve_answer(state)
    if state.get("conversation_id"):
        await repository.append_message(state["conversation_id"], "assistant",
                                        content=answer or None)
    return {}
