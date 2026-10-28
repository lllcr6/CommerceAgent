from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool
from pydantic import Field

from app.tools import registry
from app.tools.builtin.orders import NOT_OWNED
from app.tools.business import owns_order


@tool
async def submit_refund(
    order_id: Annotated[str, Field(description="Exact customer-owned order number")],
    user_id: Annotated[str, InjectedToolArg],
    reason: Annotated[str | None, Field(description="Optional reason; the user must confirm the final reason in the form")] = None,
) -> dict:
    """Offer a refund-request form after verified eligibility and explicit action consent.
    An eligibility question is not consent. This tool does not issue a payment
    refund. A request is saved only after the user confirms the form.
    User identity is injected; do not supply user_id.
    """

    if not await owns_order(user_id, order_id):
        return dict(NOT_OWNED)
    return {"status": "awaiting_confirmation", "order_id": order_id}


registry.register(registry.spec_from_langchain_tool(
    submit_refund, source="builtin", inject_user_id=True))
