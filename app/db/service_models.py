"""Additive tables: existing conversation/message schema remains compatible."""
from datetime import datetime
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, JSON, func, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.db.types import BIGINT_ID

CID = BIGINT_ID

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="user")

class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)

class HumanSession(Base):
    __tablename__ = "human_sessions"
    conversation_id: Mapped[int] = mapped_column(CID, ForeignKey("conversations.id"), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), default="Customer request")
    rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class DemoOrder(Base):
    __tablename__ = "demo_orders"
    order_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="paid")
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    product: Mapped[str] = mapped_column(String(100))
    tracking_no: Mapped[str] = mapped_column(String(128), unique=True)
    return_code: Mapped[str] = mapped_column(String(32), default="NONE")
    warranty_code: Mapped[str] = mapped_column(String(32), default="IN_WARRANTY")
    warranty_until: Mapped[str] = mapped_column(String(32), default="2027-10-20")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class LogisticsEvent(Base):
    __tablename__ = "logistics_events"
    id: Mapped[int] = mapped_column(CID, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("demo_orders.order_id"), index=True)
    status_code: Mapped[str] = mapped_column(String(32))
    city: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class BusinessAudit(Base):
    __tablename__ = "business_audit"
    id: Mapped[int] = mapped_column(CID, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(String(96))
    changes: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

SERVICE_TABLES = [Account.__table__, LoginSession.__table__, HumanSession.__table__,
                  DemoOrder.__table__, LogisticsEvent.__table__, BusinessAudit.__table__]


class TicketWorkflow(Base):
    __tablename__ = "ticket_workflows"
    ticket_no: Mapped[str] = mapped_column(ForeignKey("tickets.ticket_no"), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("demo_orders.order_id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TicketEvent(Base):
    __tablename__ = "ticket_events"
    id: Mapped[int] = mapped_column(CID, primary_key=True, autoincrement=True)
    ticket_no: Mapped[str] = mapped_column(ForeignKey("tickets.ticket_no"), index=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    visibility: Mapped[str] = mapped_column(String(16), default="public")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


SERVICE_TABLES.extend([TicketWorkflow.__table__, TicketEvent.__table__])


class ChatGeneration(Base):
    __tablename__ = "chat_generations"
    conversation_id: Mapped[int] = mapped_column(CID, ForeignKey("conversations.id"), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), unique=True)
    state: Mapped[str] = mapped_column(String(16), index=True)
    frames: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


SERVICE_TABLES.append(ChatGeneration.__table__)
