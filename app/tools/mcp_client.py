"""Discover live MCP tools per request. Local policy controls permissions and formatting."""
import asyncio
import logging

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import settings
from app.tools import registry
from app.tools.registry import ToolSpec

logger = logging.getLogger(__name__)


def _translate(mapping: dict[str, str], code):
    return mapping.get(code, code)


def _fmt_logistics(d: dict) -> dict:
    return {"tracking_no": d.get("tracking_no"),
            "status": _translate({"PICKED_UP": "Picked up", "IN_TRANSIT": "In transit",
                                  "DELIVERING": "Out for delivery", "DELIVERED": "Delivered"}, d.get("status_code")),
            "current_city": d.get("current_city"), "trace": d.get("trace")}


def _fmt_warranty(d: dict) -> dict:
    return {"order_id": d.get("order_id"),
            "warranty": _translate({"IN_WARRANTY": "Under warranty", "EXPIRED": "Warranty expired"}, d.get("warranty_code")),
            "warranty_until": d.get("warranty_until")}


def _fmt_return(d: dict) -> dict:
    return {"order_id": d.get("order_id"),
            "return_status": _translate({"AUDITING": "Under review", "RETURNING": "Return in progress",
                                         "REFUNDED": "Refunded", "NONE": "No return request"}, d.get("return_code")),
            "updated_at": d.get("updated_at")}


FORMATTERS = {"query_logistics": _fmt_logistics, "query_warranty": _fmt_warranty,
              "query_return_status": _fmt_return}

_client: MultiServerMCPClient | None = None


def _connections() -> dict:
    return {
        "logistics": {"transport": "streamable_http", "url": settings.mcp_logistics_url},
        "aftersales": {"transport": "streamable_http", "url": settings.mcp_aftersales_url},
    }


def get_client() -> MultiServerMCPClient:
    global _client
    if _client is None:

        _client = MultiServerMCPClient(_connections(), handle_tool_errors=False)
    return _client


async def _get_tools_of(*, server_name: str):
    """Fetch tools from a single MCP server; isolated for testing."""
    return await get_client().get_tools(server_name=server_name)


async def fetch_mcp_specs() -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for server in _connections():
        try:


            tools = await asyncio.wait_for(_get_tools_of(server_name=server),
                                           timeout=settings.mcp_tool_timeout)
        except Exception as e:
            logger.warning("MCP server %s is unreachable; skipping its tools for this request: %s", server, type(e).__name__)
            continue
        for t in tools:
            specs.append(registry.spec_from_langchain_tool(
                t, source="mcp", mcp_server=server, format_result=FORMATTERS.get(t.name)))
    return specs
