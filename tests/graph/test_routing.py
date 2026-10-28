import pytest
from langchain_core.messages import AIMessage

from app.config import settings
from app.graph.routing import (
    confidence_gate, route_by_intent, should_continue, INTENT_TO_ROUTE,
)


@pytest.mark.parametrize("intent,expect", [
    ("complaint", "escalate"),
    ("chitchat", "fallback_script"),
    ("other", "fallback_script"),
    ("product_policy", "knowledge"),
    ("return_refund", "refund_flow"),
    ("warranty_support", "business"),
    ("human_support", "business"),
    ("shipping", "business"),
    ("order_status", "business"),
])
def test_route_by_intent_five_outlets(intent, expect):
    assert route_by_intent({"intent": intent}) == expect


def test_route_by_intent_unknown_defaults_business():
    assert route_by_intent({"intent": "火星语"}) == "business"
    assert route_by_intent({}) == "business"


def test_intent_to_route_covers_nine_classes():
    assert set(INTENT_TO_ROUTE) == {
        "complaint", "chitchat", "other", "product_policy", "return_refund", "warranty_support", "human_support", "shipping", "order_status"}


def test_confidence_gate():
    assert confidence_gate({"evidence_strong": True}) == "strong"
    assert confidence_gate({"evidence_strong": False}) == "weak"
    assert confidence_gate({}) == "weak"


def test_should_continue_stops_when_no_tool_calls():
    state = {"messages": [AIMessage("答完了")], "steps": 1, "tokens_used": 0}
    assert should_continue(state) == "stop"


def test_should_continue_continues_on_tool_calls():
    ai = AIMessage("", tool_calls=[{"name": "query_order", "args": {}, "id": "1"}])
    state = {"messages": [ai], "steps": 1, "tokens_used": 0}
    assert should_continue(state) == "continue"


def test_should_continue_stops_on_step_cap():
    ai = AIMessage("", tool_calls=[{"name": "query_order", "args": {}, "id": "1"}])
    state = {"messages": [ai], "steps": settings.max_agent_steps, "tokens_used": 0}
    assert should_continue(state) == "stop"


def test_token_spend_does_not_stop_react_loop():


    ai = AIMessage("", tool_calls=[{"name": "query_order", "args": {}, "id": "1"}])
    state = {"messages": [ai], "steps": 1, "tokens_used": 10_000_000}
    assert should_continue(state) == "continue"
