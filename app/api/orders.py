"""Customer order details and ticket creation, always scoped to the login session."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
import app.db.base as db
from app.auth import customer
from app.db.models import Conversation, Message
from app.db.service_models import DemoOrder, LogisticsEvent
from app.db.repository import add_ticket
from app.business_store import order_dict

router = APIRouter(prefix='/api/orders')

async def owned_order(session, oid, user):
    order = await session.get(DemoOrder, oid)
    if not order or order.user_id != user.id:
        raise HTTPException(404, 'Order not found.')
    return order

@router.get('/{oid}')
async def detail(oid: str, user=Depends(customer)):
    async with db.async_session() as s:
        order = await owned_order(s, oid, user)
        events = (await s.scalars(select(LogisticsEvent).where(LogisticsEvent.order_id == oid).order_by(LogisticsEvent.id.desc()))).all()
        return {'order': order_dict(order), 'events': [
            {'status_code': e.status_code, 'city': e.city, 'description': e.description,
             'created_at': e.created_at.isoformat()} for e in events]}

class OrderTicketRequest(BaseModel):
    ticket_type: Literal['after_sales', 'complaint', 'question'] = 'after_sales'
    description: str = Field(min_length=1, max_length=8000)

    @field_validator('description')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("Describe your issue")
        return value.strip()

@router.post('/{oid}/tickets')
async def create_ticket(oid: str, req: OrderTicketRequest, user=Depends(customer)):
    async with db.async_session() as s:
        await owned_order(s, oid, user)
        conv = Conversation(user_id=user.id)
        s.add(conv)
        await s.flush()
        s.add(Message(conversation_id=conv.id, role='user', content=f'[Order ticket: {oid}】\n{req.description}'))
        number = await add_ticket(s, conv, req.description, req.ticket_type, oid)
        await s.commit()
        return {'ticket_no': number, 'conversation_id': conv.id, 'state': 'pending'}
