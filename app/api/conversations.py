"""Conversation lists and history for customer conversation switching."""
from fastapi import APIRouter, HTTPException, Depends

from app.db import repository
from app.auth import current_user, customer
from app.access import conversation_access

router = APIRouter()


@router.get("/api/conversations")
async def list_conversations(user=Depends(customer)):
    user_id = user.id
    items = await repository.list_conversations(user_id)
    return {"items": items}


@router.get("/api/conversations/{conversation_id}/messages")
async def list_messages(conversation_id: int, user=Depends(current_user)):
    await conversation_access(conversation_id, user)
    if await repository.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    msgs = await repository.list_dialog_messages(conversation_id)
    return {"items": [
        {"role": m.role, "content": m.content or "",
         "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in msgs
    ]}
