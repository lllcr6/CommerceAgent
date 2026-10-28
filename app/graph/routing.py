from langchain_core.messages import AIMessage

from app.config import settings


INTENT_TO_ROUTE: dict[str, str] = {
    "complaint": "escalate",
    "chitchat": "fallback_script",
    "other": "fallback_script",
    "product_policy": "knowledge",
    "return_refund": "refund_flow",
    "warranty_support": "business",
    "human_support": "business",
    "shipping": "business",
    "order_status": "business",
}
def route_by_intent(state) -> str:
    """Route intents; unknown intents use the business agent."""
    return INTENT_TO_ROUTE.get(state.get("intent", ""), "business")


def confidence_gate(state) -> str:
    """Route strong evidence to generation and weak evidence to fallback."""
    return "strong" if state.get("evidence_strong") else "weak"


def should_continue(state) -> str:
    """Stop on a final answer or the maximum ReAct step count. Usage accounting remains separate from the loop limit."""
    last = state["messages"][-1]
    has_tool_calls = isinstance(last, AIMessage) and bool(last.tool_calls)
    if not has_tool_calls:
        return "stop"
    if state.get("steps", 0) >= settings.max_agent_steps:
        return "stop"
    return "continue"
