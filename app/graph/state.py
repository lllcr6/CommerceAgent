from typing import Annotated
from typing_extensions import TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def merge_dict(a: dict | None, b: dict | None) -> dict:
    """Merge trace fields; None explicitly resets prior-turn data because merging an empty dictionary does not clear it."""
    if b is None:
        return {}
    return {**(a or {}), **b}


class ConversationState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    summary: str
    summary_upto_msg_id: int
    layer1_from_msg_id: int
    human_requested: bool
    user_id: str
    conversation_id: int
    intent: str
    resolved_query: str
    intent_confidence: float
    order_id: str
    order_data: dict
    route: str             # knowledge | business | complaint | chitchat
    evidence: str
    citations: list
    evidence_strong: bool
    evidence_confidence: float
    fallback_source: str
    retrieved_snapshot: list
    answer: str
    steps: int
    tokens_used: int
    suggested_actions: list  # [{"type": "transfer_human"} | {"type": "create_ticket", "draft": {...}}]
    trace: Annotated[dict, merge_dict]
