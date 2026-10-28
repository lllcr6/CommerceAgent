from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.config import settings
from app.core import memory


def _dialogue(turns: int, reply_chars: int = 600) -> list:

    msgs = []
    for i in range(1, turns + 1):
        msgs.append(HumanMessage(f"第{i}轮的问题", id=f"db-{i * 2 - 1}"))
        msgs.append(AIMessage("答" * reply_chars))
    return msgs


def test_user_text_never_compressed():

    msgs = [HumanMessage("我之前问的那个跑鞋，订单 202603150088")]
    assert memory.to_layer2(msgs)[0].content == msgs[0].content


def test_reply_truncated_beyond_threshold():
    short, long = "好的", "答" * 500
    assert memory.compress_reply(short) == short
    out = memory.compress_reply(long)
    assert len(out) < len(long)
    assert out.startswith("答" * settings.layer2_reply_keep_chars)


def test_small_tool_result_kept_large_one_dropped():
    small = '{"order_id": "1001", "status": "paid"}'
    assert memory.compress_tool_result("query_order", small) == small
    big = memory.compress_tool_result("query_faq", "证据" * 2000)
    assert "query_faq" in big and len(big) < 60


def test_layer2_is_idempotent():

    msgs = _dialogue(3) + [ToolMessage("证据" * 2000, tool_call_id="t1", name="query_faq")]
    once = memory.to_layer2(msgs)
    twice = memory.to_layer2(once)
    assert [m.content for m in once] == [m.content for m in twice]


def test_layer2_keeps_message_ids():

    msgs = _dialogue(2)
    for src, out in zip(msgs, memory.to_layer2(msgs)):
        assert out.id == src.id


def test_build_window_without_anchor_is_single_layer():
    msgs = _dialogue(3)
    assert memory.build_window(msgs, 0, 0, max_tokens=10_000) == msgs


def test_build_window_splits_by_anchor():

    msgs = _dialogue(6)
    out = memory.build_window(msgs, 0, layer1_from_msg_id=5, max_tokens=100_000)
    assert "abridged" in out[1].content
    assert "abridged" not in out[-1].content


def test_layer_tokens_splits_at_anchor():
    msgs = _dialogue(6)
    l2, l1 = memory.layer_tokens(msgs, 0, layer1_from_msg_id=5)
    assert l2 > 0 and l1 > 0
    whole = memory.count_tokens(msgs)
    assert l2 + l1 < whole


def test_next_layer1_from_moves_boundary_back():

    msgs = _dialogue(10)
    tight = memory.next_layer1_from(msgs, 0, layer1_budget=500)
    loose = memory.next_layer1_from(msgs, 0, layer1_budget=5_000)
    assert tight > loose


def test_next_layer1_from_returns_zero_when_budget_is_ample():
    msgs = _dialogue(3)
    assert memory.next_layer1_from(msgs, 0, layer1_budget=10**6) == 0


def test_compression_preserves_tool_calls():

    from langchain_core.messages import AIMessage, ToolMessage
    call = {"name": "query_order", "args": {"order_id": "1001"}, "id": "call_abc", "type": "tool_call"}
    msgs = [AIMessage("I will check the order details. " * 20, id="a1", tool_calls=[call]),
            ToolMessage("订单数据" * 200, tool_call_id="call_abc", name="query_order", id="t1")]
    out = memory.to_layer2(msgs)
    assert out[0].content.endswith("…(abridged)")
    assert [c["id"] for c in out[0].tool_calls] == ["call_abc"]
    assert out[1].tool_call_id == "call_abc"
