"""Independent ticket queue, assignment, records, completion, and scoped order access."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update, or_
import app.db.base as db
from app.auth import current_user, staff, administrator
from app.access import conversation_access
from app.db.models import Ticket, Conversation, Message
from app.db.service_models import TicketWorkflow, TicketEvent, Account, DemoOrder
from app.db.ticket_workflow import event
from app.api.service import OrderUpdate, apply_order_update, ORDER_STATUS_LABELS, RETURN_STATUS_LABELS
from app.business_store import order_dict

router = APIRouter(prefix="/api/tickets")
LABEL = {"pending": "Awaiting support", "processing": "In progress", "completed": "Completed"}

class VersionRequest(BaseModel):
    version: int = Field(ge=1)

class AssignmentRequest(VersionRequest):
    assignee_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="", max_length=1000)

class RecordRequest(VersionRequest):
    content: str = Field(min_length=1, max_length=8000)
    visibility: Literal["public", "internal"] = "internal"

    @field_validator("content")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("Content cannot be empty")
        return value.strip()

class CompletionRequest(VersionRequest):
    resolution: str = Field(min_length=1, max_length=8000)

    @field_validator("resolution")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("A public resolution is required to complete a ticket")
        return value.strip()

class LinkOrderRequest(VersionRequest):
    order_id: str = Field(min_length=1, max_length=96)


def view(ticket, workflow, owner, principal):
    return {"ticket_no": ticket.ticket_no, "conversation_id": ticket.conversation_id,
            "user_id": owner, "ticket_type": ticket.ticket_type, "description": ticket.description,
            "state": workflow.state, "status": LABEL[workflow.state],
            "assignee_id": workflow.assignee_id if principal.role != "user" else None,
            "order_id": workflow.order_id, "version": workflow.version,
            "resolution": workflow.resolution, "created_at": ticket.created_at.isoformat(),
            "updated_at": workflow.updated_at.isoformat(),
            "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None,
            "can_claim": principal.role == "support" and workflow.state == "pending" and not workflow.assignee_id,
            "can_manage": workflow.state == "processing" and workflow.assignee_id == principal.id and principal.role == "support",
            "can_assign": principal.role == "admin" and workflow.state != "completed"}

async def load(session, number, principal, *, manage=False):
    ticket = await session.get(Ticket, number)
    workflow = await session.get(TicketWorkflow, number, with_for_update=manage)
    if not ticket or not workflow:
        raise HTTPException(404, "Ticket not found.")
    conv = await session.get(Conversation, ticket.conversation_id)
    allowed = (conv.user_id == principal.id if principal.role == "user" else
               principal.role == "admin" or workflow.assignee_id == principal.id or
               (workflow.state == "pending" and workflow.assignee_id is None))
    if not allowed:
        raise HTTPException(404, "Ticket not found.")
    if manage:
        if principal.role != "support" or workflow.assignee_id != principal.id:
            raise HTTPException(403, "Only the assigned specialist can update this ticket")
        if workflow.state != "processing":
            raise HTTPException(409, "This ticket is completed or has not been claimed")
    return ticket, workflow, conv


def check_version(workflow, version):
    if workflow.version != version:
        raise HTTPException(409, "The ticket changed. Refresh and try again.")

@router.get("")
async def list_tickets(scope: Literal["mine", "pending", "all", "conversation"] | None = None,
                       conversation_id: int | None = None,
                       state: Literal["pending", "processing", "completed"] | None = None,
                       user=Depends(current_user)):
    async with db.async_session() as s:
        query = select(Ticket, TicketWorkflow, Conversation.user_id).join(TicketWorkflow, TicketWorkflow.ticket_no == Ticket.ticket_no).join(Conversation, Conversation.id == Ticket.conversation_id)
        scope = scope or ("conversation" if conversation_id is not None else "all" if user.role == "admin" else "mine")
        if user.role == "user":
            if scope not in ("mine", "conversation"):
                raise HTTPException(403, "You can only view your own tickets")
            query = query.where(Conversation.user_id == user.id)
        elif scope == "pending":
            query = query.where(TicketWorkflow.state == "pending", TicketWorkflow.assignee_id.is_(None))
        elif scope == "mine":
            query = query.where(TicketWorkflow.assignee_id == user.id)
        elif scope == "all":
            if user.role != "admin":
                raise HTTPException(403, "Administrator access required.")
        elif scope == "conversation":
            if conversation_id is None:
                raise HTTPException(400, "Select a conversation")
            await conversation_access(conversation_id, user)
        if conversation_id is not None:
            query = query.where(Ticket.conversation_id == conversation_id)
        if state:
            query = query.where(TicketWorkflow.state == state)
        rows = (await s.execute(query.order_by(Ticket.created_at.desc(), Ticket.ticket_no.desc()))).all()
        return {"items": [view(t, w, owner, user) for t, w, owner in rows]}

@router.get("/assignees")
async def assignees(user=Depends(administrator)):
    async with db.async_session() as s:
        users = (await s.scalars(select(Account).where(Account.role == "support").order_by(Account.id))).all()
        return {"items": [{"id": account.id, "role": account.role} for account in users]}

@router.get("/{number}")
async def detail(number: str, user=Depends(current_user)):
    async with db.async_session() as s:
        ticket, workflow, conv = await load(s, number, user)
        out = view(ticket, workflow, conv.user_id, user)
        privileged = user.role == "admin" or (user.role == "support" and workflow.assignee_id == user.id)
        events = select(TicketEvent).where(TicketEvent.ticket_no == number)
        if not privileged:
            events = events.where(TicketEvent.visibility == "public")
        rows = (await s.scalars(events.order_by(TicketEvent.id))).all()
        out["records"] = [{"id": e.id, "action": e.action, "visibility": e.visibility,
                           "content": e.content, "actor_id": e.actor_id if privileged or e.actor_id == user.id else "Customer" if e.actor_id == conv.user_id else "Support",
                           "created_at": e.created_at.isoformat()} for e in rows]
        # Ticket assignment grants this scoped context, never general conversation access.
        out["messages"] = []
        out["order"] = None
        if privileged or conv.user_id == user.id:
            msgs = (await s.scalars(select(Message).where(Message.conversation_id == conv.id,
                    Message.role.in_(["user", "assistant"])).order_by(Message.id))).all()
            out["messages"] = [{"role": m.role, "content": m.content or ""} for m in msgs]
            if workflow.order_id:
                order = await s.get(DemoOrder, workflow.order_id)
                if order and order.user_id == conv.user_id:
                    out["order"] = order_dict(order)
        return out

@router.post("/{number}/claim")
async def claim(number: str, req: VersionRequest, user=Depends(staff)):
    async with db.async_session() as s:
        result = await s.execute(update(TicketWorkflow).where(
            TicketWorkflow.ticket_no == number, TicketWorkflow.state == "pending",
            TicketWorkflow.assignee_id.is_(None), TicketWorkflow.version == req.version
        ).values(state="processing", assignee_id=user.id, version=TicketWorkflow.version + 1))
        if result.rowcount != 1:
            raise HTTPException(409, "This ticket has been claimed or changed. Please refresh.")
        event(s, number, user.id, "claimed", "A support specialist is working on this ticket.")
        await s.commit()
    return {"state": "processing"}

@router.post("/{number}/assign")
async def assign(number: str, req: AssignmentRequest, user=Depends(administrator)):
    async with db.async_session() as s:
        ticket = await s.get(Ticket, number)
        workflow = await s.get(TicketWorkflow, number, with_for_update=True)
        if not ticket or not workflow:
            raise HTTPException(404, "Ticket not found.")
        check_version(workflow, req.version)
        if workflow.state == "completed":
            raise HTTPException(409, "Completed tickets cannot be reassigned.")
        target = await s.get(Account, req.assignee_id)
        if not target or target.role != "support":
            raise HTTPException(400, "Choose a support account.")
        old = workflow.assignee_id
        if old == target.id:
            raise HTTPException(409, "This agent is already the current owner.")
        workflow.assignee_id = target.id
        workflow.state = "processing"
        workflow.version += 1
        event(s, number, user.id, "assigned" if not old else "reassigned", "The ticket has been assigned to a support specialist.")
        event(s, number, user.id, "assignment_detail", f"Assigned specialist: {old or 'Unassigned'} → {target.id}" + (f"; reason: {req.reason}" if req.reason else ""), "internal")
        await s.commit()
    return {"state": "processing", "assignee_id": target.id}

@router.post("/{number}/records")
async def add_record(number: str, req: RecordRequest, user=Depends(staff)):
    async with db.async_session() as s:
        ticket, workflow, conv = await load(s, number, user, manage=True)
        check_version(workflow, req.version)
        event(s, number, user.id, "update" if req.visibility == "public" else "note", req.content, req.visibility)
        workflow.version += 1
        await s.commit()
    return {"ok": True}

@router.post("/{number}/complete")
async def complete(number: str, req: CompletionRequest, user=Depends(staff)):
    async with db.async_session() as s:
        ticket, workflow, conv = await load(s, number, user, manage=True)
        check_version(workflow, req.version)
        workflow.state = "completed"
        workflow.resolution = req.resolution
        workflow.completed_at = datetime.utcnow()
        workflow.version += 1
        ticket.status = "completed"
        event(s, number, user.id, "completed", req.resolution)
        await s.commit()
    return {"state": "completed", "resolution": req.resolution}

@router.patch("/{number}", deprecated=True)
async def legacy_complete(number: str, req: CompletionRequest, user=Depends(staff)):
    # The old one-click endpoint must not bypass assignment or a required result.
    return await complete(number, req, user)

@router.patch("/{number}/order")
async def link_order(number: str, req: LinkOrderRequest, user=Depends(staff)):
    async with db.async_session() as s:
        ticket, workflow, conv = await load(s, number, user, manage=True)
        check_version(workflow, req.version)
        order = await s.get(DemoOrder, req.order_id)
        if not order or order.user_id != conv.user_id:
            raise HTTPException(404, "Order not found.")
        workflow.order_id = order.order_id
        workflow.version += 1
        event(s, number, user.id, "order_linked", f"Linked order: {order.order_id}", "internal")
        await s.commit()
    return {"order_id": order.order_id}

@router.patch("/{number}/orders/{oid}")
async def update_order(number: str, oid: str, req: OrderUpdate, user=Depends(staff)):
    async with db.async_session() as s:
        ticket, workflow, conv = await load(s, number, user, manage=True)
        if workflow.order_id != oid:
            raise HTTPException(404, "This order is not linked to the ticket.")
        result = await apply_order_update(s, oid, req, user.id, conv.user_id)
        workflow.version += 1
        event(s, number, user.id, "order_updated", f"Updated linked order: {oid}; order status: {ORDER_STATUS_LABELS.get(result['status'], result['status'])}; return status: {RETURN_STATUS_LABELS.get(result['return_code'], result['return_code'])}" + (f"; tracking: {req.status_code} {req.city} {req.description}" if req.status_code else ""), "internal")
        await s.commit()
    return {"order": result}
