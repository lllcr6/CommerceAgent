"""Internal logistics MCP service sharing the application database. MOCK_DELAY_SECONDS supports timeout testing."""
import asyncio
import os
import random
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP("logistics",
              host="127.0.0.1", port=int(os.environ.get("PORT", "8101")))

_DELAY = float(os.environ.get("MOCK_DELAY_SECONDS", "0"))
_STATUS_CODES = ["PICKED_UP", "IN_TRANSIT", "DELIVERING", "DELIVERED"]
_CITIES = ["Los Angeles, CA", "Phoenix, AZ", "Denver, CO", "Chicago, IL", "New York, NY"]


@mcp.tool()
async def query_logistics(
    tracking_no: Annotated[str, Field(description="Exact tracking reference returned by query_order; demo references start with DEMO-US-")],
) -> dict:
    """Look up carrier events, current city, and tracking history using a tracking reference.
    First use query_order to obtain tracking_no; an order number is not a tracking reference.
    All records are simulated demo data.
    """
    if _DELAY > 0:
        await asyncio.sleep(_DELAY)
    from app.business_store import logistics
    return await logistics(tracking_no)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
