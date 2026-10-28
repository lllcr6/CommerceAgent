import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.prompts import AGENT_SYSTEM
from app.graph.nodes import _agent_messages

EVIDENCE = "[1] 退货政策: 7天无理由"
ORDER = {"order_id": "1001", "status": "delivered", "product": "猫粮 5kg"}

STATES = [
    ("business", {"route": "business", "messages": [HumanMessage("订单1001到哪了")]}),
    ("knowledge", {"route": "knowledge", "evidence": EVIDENCE,
                   "messages": [HumanMessage("能退吗")]}),
    ("refund", {"route": "refund_flow", "evidence": EVIDENCE, "order_data": ORDER,
                "messages": [HumanMessage("这单能退吗")]}),
    ("knowledge+摘要", {"route": "knowledge", "evidence": EVIDENCE,
                        "summary": "用户问过订单1001", "messages": [HumanMessage("能退吗")]}),
]


@pytest.mark.parametrize("name,state", STATES, ids=[s[0] for s in STATES])
def test_system_message_is_always_the_static_prompt(name, state):

    msgs = _agent_messages(state)
    assert isinstance(msgs[0], SystemMessage)
    assert msgs[0].content == AGENT_SYSTEM


def test_system_prefix_identical_across_routes():

    heads = {_agent_messages(s)[0].content for _, s in STATES}
    assert len(heads) == 1


@pytest.mark.parametrize("name,state", STATES, ids=[s[0] for s in STATES])
def test_exactly_one_system_message(name, state):

    assert sum(isinstance(m, SystemMessage) for m in _agent_messages(state)) == 1


@pytest.mark.parametrize("name,state", STATES, ids=[s[0] for s in STATES])
def test_volatile_payload_never_lands_in_any_system_message(name, state):

    systems = " ".join(m.content for m in _agent_messages(state) if isinstance(m, SystemMessage))
    for volatile in ("[1] 退货政策", "猫粮 5kg", "已检索到的知识证据", "退款判定任务",
                     "用户问过订单1001"):
        assert volatile not in systems


def test_step1_prompt_is_strict_prefix_of_step2():

    base = {"route": "refund_flow", "evidence": EVIDENCE, "order_data": ORDER}
    q = HumanMessage("这单能退吗", id="db-1")
    step1 = _agent_messages({**base, "messages": [q]})
    step2 = _agent_messages({**base, "messages": [
        q,
        AIMessage("", tool_calls=[{"name": "query_order", "args": {"order_id": "1001"},
                                   "id": "call_1"}]),
        ToolMessage("delivered", tool_call_id="call_1", name="query_order"),
    ]})
    shape = lambda ms: [(m.type, m.content) for m in ms]      # noqa: E731
    assert shape(step2)[:len(step1)] == shape(step1)


def test_turn_context_is_not_written_back_to_state():

    msgs_in = [HumanMessage("能退吗")]
    state = {"route": "knowledge", "evidence": EVIDENCE, "messages": msgs_in}
    _agent_messages(state)
    assert state["messages"] is msgs_in and len(msgs_in) == 1
