"""Shared built-in and MCP tool registry. Local write-tool policy overrides external server declarations."""
import importlib
import logging
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


WRITE_TOOLS: set[str] = {"create_ticket", "request_human"}


@dataclass
class ToolSpec:
    name: str
    description: str
    json_schema: dict
    tool: BaseTool
    permission: str              # "read" | "write"
    source: str                  # "builtin" | "mcp"
    mcp_server: str | None = None
    timeout: float | None = None
    max_retries: int | None = None
    inject_conversation: bool = False
    inject_user_id: bool = False
    format_result: Callable[[dict], dict] | None = None


_BUILTIN: dict[str, ToolSpec] = {}
_scanned = False


def permission_for(name: str) -> str:
    return "write" if name in WRITE_TOOLS else "read"


def _json_schema_of(tool: BaseTool) -> dict:
    """Return model-visible JSON Schema, excluding injected identity arguments."""
    raw = getattr(tool, "args_schema", None)
    if isinstance(raw, dict):
        return raw
    tcs = getattr(tool, "tool_call_schema", None) or raw
    return tcs.model_json_schema()


def spec_from_langchain_tool(tool: BaseTool, *, source: str, mcp_server: str | None = None,
                             timeout: float | None = None, max_retries: int | None = None,
                             inject_conversation: bool = False, inject_user_id: bool = False,
                             format_result: Callable | None = None) -> ToolSpec:
    return ToolSpec(name=tool.name, description=tool.description or "",
                    json_schema=_json_schema_of(tool), tool=tool,
                    permission=permission_for(tool.name), source=source, mcp_server=mcp_server,
                    timeout=timeout, max_retries=max_retries,
                    inject_conversation=inject_conversation, inject_user_id=inject_user_id,
                    format_result=format_result)


def register(spec: ToolSpec) -> None:
    if spec.name in _BUILTIN:
        logger.warning("Duplicate tool ignored: name=%s; keeping the first registration", spec.name)
        return
    _BUILTIN[spec.name] = spec


def scan_builtin() -> None:
    """Import built-in modules to register tools once during startup."""
    global _scanned
    if _scanned:
        return
    _scanned = True
    from app.tools import builtin as pkg
    for m in pkgutil.iter_modules(pkg.__path__):
        try:
            importlib.import_module(f"{pkg.__name__}.{m.name}")
        except Exception:
            logger.exception("Built-in tool module import failed; skipping module=%s", m.name)
    logger.info("Registered built-in tools: %s", sorted(_BUILTIN))


def builtin_specs() -> list[ToolSpec]:
    scan_builtin()
    return list(_BUILTIN.values())


def get_builtin_spec(name: str) -> ToolSpec | None:
    scan_builtin()
    return _BUILTIN.get(name)


async def get_all_specs() -> list[ToolSpec]:
    """Merge built-in and live MCP tools, keeping the first name registration. Preserve insertion order for stable cached prompt prefixes."""
    from app.tools import mcp_client
    merged: dict[str, ToolSpec] = {s.name: s for s in builtin_specs()}
    for s in await mcp_client.fetch_mcp_specs():
        if s.name in merged:
            logger.warning("Duplicate MCP tool ignored: name=%s server=%s", s.name, s.mcp_server)
            continue
        merged[s.name] = s
    return list(merged.values())
