from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graph.nodes import _agent_messages, _history_text


def _state(n_turns=3, summary="", upto=0):
    msgs = []
    db_id = 1
    for i in range(n_turns):
        msgs.append(HumanMessage(f"问题{i}", id=f"db-{db_id}"))
        msgs.append(AIMessage(f"回答{i}"))
        db_id += 2
    return {"messages": msgs, "summary": summary, "summary_upto_msg_id": upto}


def test_agent_messages_order_with_summary():

    ms = _agent_messages(_state(summary="用户问过订单1001", upto=0))
    assert isinstance(ms[0], SystemMessage) and "PawPal" in ms[0].content
    assert sum(isinstance(m, SystemMessage) for m in ms) == 1
    assert isinstance(ms[1], HumanMessage)
    ctx = [m for m in ms if "订单1001" in (m.content or "")]
    assert ctx and not isinstance(ctx[0], SystemMessage)


def test_agent_messages_no_summary_no_extra_system():
    ms = _agent_messages(_state(summary="", upto=0))
    assert isinstance(ms[0], SystemMessage)
    assert not isinstance(ms[1], SystemMessage)


def test_agent_messages_window_cut_by_boundary():
    ms = _agent_messages(_state(n_turns=6, summary="早期摘要", upto=6))
    win = [m for m in ms if not isinstance(m, SystemMessage)]
    assert win[0].id == "db-7"


def test_history_text_prepends_summary_and_windows():
    text = _history_text(_state(n_turns=6, summary="用户问过订单1001", upto=6))
    assert text.startswith("(Earlier conversation summary: 用户问过订单1001")
    assert "问题0" not in text
    assert "问题3" in text


def test_history_text_no_summary_same_as_before():
    text = _history_text(_state(n_turns=2))
    assert "摘要" not in text and "问题0" in text


def test_log_model_context_shows_summary_and_window(caplog):
    import logging
    from app.graph.nodes import _agent_messages, _log_model_context
    state = _state(n_turns=6, summary="用户问过订单1001,留了手机13800138000", upto=6)
    msgs = _agent_messages(state)
    with caplog.at_level(logging.INFO, logger="app.graph.nodes"):
        _log_model_context(state, msgs)
    text = caplog.text
    assert "Model context" in text
    assert "订单1001" in text
    assert "[human] '问题3" in text
    assert "问题0" not in text


def _layered_state(layer1_from: int):

    long_reply = "This is a long support response. " * 30
    msgs = []
    for i, db_id in enumerate((1, 3, 5)):
        msgs.append(HumanMessage(f"问题{i}", id=f"db-{db_id}"))
        msgs.append(AIMessage(long_reply + f"第{i}轮"))
    return {"messages": msgs, "summary": "", "summary_upto_msg_id": 0,
            "layer1_from_msg_id": layer1_from}


def test_recent_history_anchor_reaches_renderer():

    ms = _agent_messages(_layered_state(layer1_from=3))
    replies = [m.content for m in ms if isinstance(m, AIMessage)]
    assert len(replies) == 3
    assert replies[0].endswith("…(abridged)")
    assert replies[1].endswith("…(abridged)")
    assert not replies[2].endswith("…(abridged)")


def test_absent_recent_anchor_preserves_full_history():

    ms = _agent_messages(_layered_state(layer1_from=0))
    replies = [m.content for m in ms if isinstance(m, AIMessage)]
    assert not any(r.endswith("…(abridged)") for r in replies)


def test_reference_resolution_shares_agent_history_anchors():

    text = _history_text(_layered_state(layer1_from=3))
    assert "…(abridged)" in text
