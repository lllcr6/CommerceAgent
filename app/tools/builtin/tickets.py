import asyncio
from typing import Annotated, Literal

from langchain_core.tools import InjectedToolArg, tool

from app.config import settings
from app.db import repository
from app.tools import registry


@tool
async def create_ticket(
    description: str,
    ticket_type: Literal["after_sales", "complaint", "question"],
    conversation_id: Annotated[int, InjectedToolArg],
) -> dict:
    """Prepare a support ticket after an explicit request for follow-up.

    Obtain a meaningful description without inventing details. The graph presents
    a preview for customer confirmation before writing. Identity is injected.
    """
    if settings.demo_ticket_delay_seconds > 0:
        await asyncio.sleep(settings.demo_ticket_delay_seconds)
    ticket_no = await repository.create_ticket(conversation_id, description, ticket_type)
    return {"ticket_no": ticket_no, "status": "pending"}


registry.register(registry.spec_from_langchain_tool(
    create_ticket, source="builtin", inject_conversation=True))
