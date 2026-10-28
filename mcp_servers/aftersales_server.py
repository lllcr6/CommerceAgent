"""Internal warranty and return-status MCP service using simulated business data."""
import asyncio
import os
import random
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP("aftersales",
              host="127.0.0.1", port=int(os.environ.get("PORT", "8102")))

_DELAY = float(os.environ.get("MOCK_DELAY_SECONDS", "0"))


@mcp.tool()
async def query_warranty(
    order_id: Annotated[str, Field(description="Exact order number returned by query_order, for example alice-1001")],
) -> dict:
    """Look up an order's warranty status and expiration date. These are simulated order-specific records."""
    if _DELAY > 0:
        await asyncio.sleep(_DELAY)
    from app.business_store import order_snapshot
    order = await order_snapshot(order_id)
    return {"order_id": order_id, "warranty_code": order.get("warranty_code"), "warranty_until": order.get("warranty_until")}


@mcp.tool()
async def query_return_status(
    order_id: Annotated[str, Field(description="Exact order number returned by query_order, for example alice-1001")],
) -> dict:
    """Look up an order's return progress: under review, return in progress, refunded, or no request. A return authorization is not a completed refund."""
    if _DELAY > 0:
        await asyncio.sleep(_DELAY)
    from app.business_store import order_snapshot
    order = await order_snapshot(order_id)
    return {"order_id": order_id, "return_code": order.get("return_code"), "version": order.get("version")}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
