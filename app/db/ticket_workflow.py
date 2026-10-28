"""Ticket lifecycle is independent of the real-time human support lifecycle."""
from sqlalchemy import select, case
from app.db.models import Ticket
from app.db.service_models import TicketWorkflow, TicketEvent


async def backfill_workflows(session):
    # Idempotent and safe when multiple app workers start concurrently.
    source = (select(Ticket.ticket_no,
                     case((Ticket.status == "completed", "completed"), else_="pending"),
                     Ticket.created_at, Ticket.created_at, 1)
              .outerjoin(TicketWorkflow, TicketWorkflow.ticket_no == Ticket.ticket_no)
              .where(TicketWorkflow.ticket_no.is_(None)))
    columns = ["ticket_no", "state", "created_at", "updated_at", "version"]
    dialect = session.get_bind().dialect.name
    if dialect in ("mysql", "mariadb"):
        from sqlalchemy.dialects.mysql import insert
        statement = insert(TicketWorkflow).from_select(columns, source).prefix_with("IGNORE")
    else:
        from sqlalchemy.dialects.sqlite import insert
        statement = insert(TicketWorkflow).from_select(columns, source).on_conflict_do_nothing(index_elements=["ticket_no"])
    await session.execute(statement)


def event(session, ticket_no, actor_id, action, content, visibility="public"):
    session.add(TicketEvent(ticket_no=ticket_no, actor_id=actor_id, action=action,
                            content=content, visibility=visibility))
