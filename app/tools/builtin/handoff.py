from typing import Annotated
from langchain_core.tools import InjectedToolArg, tool
from app.tools import registry
import app.db.base as db
from app.db.models import Conversation
from app.db.service_models import HumanSession

@tool
async def request_human(
    reason: str,
    conversation_id: Annotated[int, InjectedToolArg],
    user_id: Annotated[str, InjectedToolArg],
) -> dict:
    """Request a human agent when explicitly requested or human review is needed.
    On success, the conversation is queued. Stop automatic replies and further
    tool execution. Conversation and user identity are injected by the system.
    """
    # Runtime already holds the conversation lifecycle lock while tools execute.
    async with db.async_session() as s:
        conv = await s.get(Conversation, conversation_id, with_for_update=True)
        if not conv or conv.user_id != user_id or conv.status == "closed":
            return {"error": "This conversation cannot be transferred."}
        h = await s.get(HumanSession, conversation_id)
        if not h:
            h = HumanSession(conversation_id=conversation_id, reason=reason[:500])
            s.add(h)
        conv.status = "handed_off"
        await s.commit()
    return {"state": h.state, "conversation_id": conversation_id}

registry.register(registry.spec_from_langchain_tool(
    request_human, source="builtin", inject_conversation=True, inject_user_id=True))
