from fastapi import Depends, HTTPException
from sqlalchemy import select
import app.db.base as db
from app.auth import current_user
from app.db.models import Conversation
from app.db.service_models import HumanSession

async def conversation_access(cid: int, user, *, write=False):
    async with db.async_session() as s:
        conv = await s.get(Conversation, cid)
        human = await s.get(HumanSession, cid)
        allowed = conv and ((user.role == "user" and conv.user_id == user.id) or (user.role == "admin" and not write) or
                   (user.role == "support" and human and human.agent_id == user.id))
        if not allowed:
            raise HTTPException(404, "Conversation not found")
        if write and conv.status == "closed":
            raise HTTPException(409, "This conversation is closed. Start a new conversation.")
        return conv
