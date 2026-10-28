import logging

from fastapi import Depends, APIRouter, HTTPException
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy.exc import SQLAlchemyError

from app.core.service_errors import KnowledgeServiceError
from app.auth import customer
from app.access import conversation_access
from app.graph import runtime
from app.graph.nodes import resolve_answer
from app.schemas.agent import AgentRequest, AgentResponse, ToolCallView, ToolResultView

logger = logging.getLogger(__name__)
router = APIRouter()


def _views_from_state(state):
    """Reconstruct tool calls and results from final graph messages."""
    calls, results = [], []
    for m in state.get("messages", []):
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                calls.append(ToolCallView(id=tc["id"], name=tc["name"], args=tc["args"]))
        elif isinstance(m, ToolMessage):
            results.append(ToolResultView(
                tool_call_id=m.tool_call_id, name=m.name or "", ok=(m.status != "error"),
                content=m.content))
    return calls, results


@router.post("/api/agent", response_model=AgentResponse)
async def run_agent(req: AgentRequest, user=Depends(customer)) -> AgentResponse:
    req.user_id = user.id
    if req.conversation_id is not None:
        conv = await conversation_access(req.conversation_id, user, write=True)
        if conv.user_id != user.id:
            raise HTTPException(403, "Only the conversation owner can start an AI reply.")
        if conv.status == "handed_off":
            raise HTTPException(409, "Use the human-support message area while a support agent is handling this conversation.")
    try:
        if req.conversation_id is None:
            from app.db import repository
            req.conversation_id = await repository.create_conversation(user.id)
        out = await runtime.run_turn(req.user_id, req.message, req.conversation_id)
    except HTTPException:
        raise
    except runtime.ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except SQLAlchemyError:
        logger.exception("Database error: user_id=%s", req.user_id)
        raise HTTPException(status_code=503, detail="The database is temporarily unavailable. Please try again shortly.")
    except KnowledgeServiceError as exc:
        logger.exception("Knowledge service failed: component=%s", exc.component)
        raise HTTPException(status_code=502, detail={"message": str(exc), "component": exc.component,
            "conversation_id": req.conversation_id, "suggested_actions": [{"type": "transfer_human"}]})
    except Exception:
        logger.exception("Graph execution failed: user_id=%s", req.user_id)
        raise HTTPException(status_code=502, detail={"message": "The model is unavailable after retries. You can contact support.", "conversation_id": req.conversation_id, "suggested_actions": [{"type": "transfer_human"}]})

    state = out["state"]
    calls, results = _views_from_state(state)
    return AgentResponse(
        conversation_id=out["conversation_id"],
        answer=resolve_answer(state),
        tool_calls=calls,
        tool_results=results,
        suggested_actions=runtime.dedup_actions(state.get("suggested_actions", [])),
        interrupt=out.get("interrupt"),
    )
