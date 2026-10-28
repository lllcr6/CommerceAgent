"""Human support lifecycle and mutable demo business data."""
import asyncio
from contextlib import asynccontextmanager
from sqlalchemy import text
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
import app.db.base as db
from app.auth import current_user, customer, staff
from app.access import conversation_access
from app.db.models import Conversation, Message, Ticket
from app.db.service_models import HumanSession, DemoOrder, LogisticsEvent, BusinessAudit
from app.business_store import order_dict

router = APIRouter()
# Shared with runtime: serialize AI turns, handoff, user messages, and closing.
# Bounded stripes avoid retaining a lock per conversation forever.
_locks = [asyncio.Lock() for _ in range(256)]
@asynccontextmanager
async def conversation_lock(cid):
    async with _locks[cid % len(_locks)]:
        # MySQL advisory lock spans independent repository transactions and workers.
        # It never locks the conversation row while graph log nodes update it.
        if db.engine.dialect.name == "mysql":
            async with db.engine.connect() as conn:
                key = f"commerce:conversation:{cid}"
                got = await conn.scalar(text("SELECT GET_LOCK(:key, 120)"), {"key": key})
                if got != 1:
                    raise HTTPException(409, "This conversation is busy. Try again shortly.")
                try:
                    yield
                finally:
                    await conn.execute(text("SELECT RELEASE_LOCK(:key)"), {"key": key})
        else:
            yield


class HandoffRequest(BaseModel):
    conversation_id: int
    reason: str = Field(default="Customer request", max_length=500)

class TextRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)

class RatingRequest(BaseModel):
    rating: Literal["unsatisfied", "okay", "satisfied"]

@router.post("/api/actions/transfer-human")
async def transfer(req: HandoffRequest, user=Depends(customer)):
    await conversation_access(req.conversation_id, user, write=True)
    async with conversation_lock(req.conversation_id):
        async with db.async_session() as s:
            conv = await s.get(Conversation, req.conversation_id, with_for_update=True)
            if conv.status == "closed":
                raise HTTPException(409, "This conversation is closed.")
            h = await s.get(HumanSession, conv.id)
            if not h:
                h = HumanSession(conversation_id=conv.id, reason=req.reason)
                s.add(h)
            conv.status = "handed_off"
            await s.commit()
            return {"conversation_id": conv.id, "state": h.state}

@router.get("/api/conversations/{cid}/service")
async def service_state(cid: int, user=Depends(current_user)):
    conv = await conversation_access(cid, user)
    async with db.async_session() as s:
        h = await s.get(HumanSession, cid)
        return {"status": conv.status, "state": h.state if h else "ai", "agent_id": h.agent_id if h else None,
                "rating": h.rating if h else None}

@router.post("/api/conversations/{cid}/human-messages")
async def user_message(cid: int, req: TextRequest, user=Depends(customer)):
    await conversation_access(cid, user, write=True)
    async with conversation_lock(cid):
        async with db.async_session() as s:
            conv = await s.get(Conversation, cid, with_for_update=True)
            h = await s.get(HumanSession, cid)
            if conv.user_id != user.id:
                raise HTTPException(403, "Only the customer in this conversation can send messages")
            if not h or h.state not in ("queued", "active") or conv.status == "closed":
                raise HTTPException(409, "This conversation is not in human support")
            s.add(Message(conversation_id=cid, role="user", content=req.message))
            await s.commit()
    return {"ok": True}

@router.post("/api/conversations/{cid}/rating")
async def rate(cid: int, req: RatingRequest, user=Depends(customer)):
    conv = await conversation_access(cid, user)
    async with db.async_session() as s:
        h = await s.get(HumanSession, cid, with_for_update=True)
        if conv.user_id != user.id:
            raise HTTPException(403, "Only the customer in this conversation can submit feedback")
        if not h or h.state != "closed":
            raise HTTPException(409, "Feedback is available after the support session ends")
        if h.rating:
            raise HTTPException(409, "Feedback already submitted")
        h.rating = req.rating
        await s.commit()
    return {"rating": req.rating}

@router.get("/api/support/queue")
async def queue(user=Depends(staff)):
    async with db.async_session() as s:
        rows = (await s.execute(select(HumanSession, Conversation.user_id)
                .join(Conversation, Conversation.id == HumanSession.conversation_id)
                .where(HumanSession.state == "queued").order_by(HumanSession.created_at))).all()
        return {"items": [{"conversation_id": h.conversation_id, "user_id": customer,
                           "reason": h.reason, "state": h.state,
                           "created_at": h.created_at.isoformat()} for h, customer in rows]}

@router.get("/api/support/mine")
async def mine(user=Depends(staff)):
    """Extract conversation answers into staging and deduplicate them. Never publish directly: human review must reject order-specific facts, personal data, and unsupported generalizations first."""
    async with db.async_session() as s:
        rows = (await s.execute(select(HumanSession, Conversation.user_id)
                .join(Conversation, Conversation.id == HumanSession.conversation_id)
                .where(HumanSession.agent_id == user.id).order_by(HumanSession.created_at.desc()))).all()
        return {"items": [{"conversation_id": h.conversation_id, "user_id": customer,
                           "state": h.state, "rating": h.rating, "reason": h.reason,
                           "created_at": h.created_at.isoformat()} for h, customer in rows]}

@router.post("/api/support/{cid}/claim")
async def claim(cid: int, user=Depends(staff)):
    async with db.async_session() as s:
        result = await s.execute(update(HumanSession).where(HumanSession.conversation_id == cid,
                    HumanSession.state == "queued", HumanSession.agent_id.is_(None)).values(state="active", agent_id=user.id))
        if result.rowcount != 1:
            raise HTTPException(409, "This conversation is already assigned or cannot be claimed")
        await s.commit()
    return {"state": "active"}

async def assigned(s, cid, user):
    h = await s.get(HumanSession, cid, with_for_update=True)
    if not h or h.agent_id != user.id:
        raise HTTPException(404, "This conversation is not assigned to you")
    if h.state != "active":
        raise HTTPException(409, "This support session is closed")
    return h

@router.post("/api/support/{cid}/reply")
async def reply(cid: int, req: TextRequest, user=Depends(staff)):
    async with conversation_lock(cid):
        async with db.async_session() as s:
            await assigned(s, cid, user)
            s.add(Message(conversation_id=cid, role="assistant", content=req.message))
            await s.commit()
    return {"ok": True}

@router.post("/api/support/{cid}/close")
async def close(cid: int, user=Depends(staff)):
    async with conversation_lock(cid):
        async with db.async_session() as s:
            conv = await s.get(Conversation, cid, with_for_update=True)
            h = await assigned(s, cid, user)
            h.state = "closed"
            conv.status = "closed"
            await s.commit()
    return {"state": "closed"}

@router.get("/api/orders")
async def my_orders(user=Depends(customer)):
    from app.business_store import list_user_orders
    return {"items": await list_user_orders(user.id)}

@router.get("/api/support/{cid}/orders")
async def customer_orders(cid: int, user=Depends(staff)):
    conv = await conversation_access(cid, user)
    from app.business_store import list_user_orders
    return {"items": await list_user_orders(conv.user_id)}

class OrderUpdate(BaseModel):
    version: int = Field(ge=1)
    status: Literal["awaiting_payment", "paid", "shipped", "delivered", "cancelled"] | None = None
    return_code: Literal["NONE", "AUDITING", "RETURNING", "REFUNDED"] | None = None
    status_code: Literal["PICKED_UP", "IN_TRANSIT", "DELIVERING", "DELIVERED"] | None = None
    city: str = Field(default="Los Angeles", min_length=1, max_length=64)
    description: str = Field(default="Support updated tracking", min_length=1, max_length=500)

ORDER_STATUS_LABELS = {"awaiting_payment": "Awaiting payment", "paid": "Paid", "shipped": "Shipped", "delivered": "Delivered", "cancelled": "Cancelled"}
RETURN_STATUS_LABELS = {"NONE": "No request", "AUDITING": "Under review", "RETURNING": "Return in progress", "REFUNDED": "Refunded"}

ORDER_NEXT = {"awaiting_payment": {"paid", "cancelled"}, "paid": {"shipped", "cancelled"}, "shipped": {"delivered"}, "delivered": set(), "cancelled": set()}
RETURN_NEXT = {"NONE": {"AUDITING"}, "AUDITING": {"RETURNING", "REFUNDED", "NONE"}, "RETURNING": {"REFUNDED"}, "REFUNDED": set()}

@router.patch("/api/support/{cid}/orders/{oid}")
async def edit_order(cid: int, oid: str, req: OrderUpdate, user=Depends(staff)):
    await conversation_access(cid, user, write=True)
    async with db.async_session() as s:
        await assigned(s, cid, user)
        conv = await s.get(Conversation, cid)
        result = await apply_order_update(s, oid, req, user.id, conv.user_id)
        await s.commit()
        return result


async def apply_order_update(s, oid, req, actor_id, owner_id):
    o = await s.get(DemoOrder, oid, with_for_update=True)
    if not o or o.user_id != owner_id:
        raise HTTPException(404, "Order not found.")
    if o.version != req.version:
        raise HTTPException(409, "The record changed. Refresh and try again.")
    for field, transitions in (("status", ORDER_NEXT), ("return_code", RETURN_NEXT)):
        value = getattr(req, field)
        if value and value != getattr(o, field):
            if value not in transitions[getattr(o, field)]:
                raise HTTPException(409, f"Invalid {field} status transition")
            setattr(o, field, value)
    if req.status_code:
        last = await s.scalar(select(LogisticsEvent).where(LogisticsEvent.order_id == oid).order_by(LogisticsEvent.id.desc()).limit(1))
        codes = ["PICKED_UP", "IN_TRANSIT", "DELIVERING", "DELIVERED"]
        if last and codes.index(req.status_code) < codes.index(last.status_code):
            raise HTTPException(409, "Tracking status cannot move backward")
        s.add(LogisticsEvent(order_id=oid, status_code=req.status_code, city=req.city, description=req.description))
    o.version += 1
    s.add(BusinessAudit(actor_id=actor_id, order_id=oid, changes=req.model_dump(exclude_none=True)))
    await s.flush()
    return order_dict(o)
