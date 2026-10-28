"""Shared tool execution pipeline: schema validation, authorization, confirmation, timeouts, retries, formatting, and audit."""
import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from langchain_core.messages import ToolMessage

from app.config import settings
from app.core import memory
from app.db import repository
from app.tools.registry import ToolSpec

logger = logging.getLogger(__name__)


_TRANSIENT = (asyncio.TimeoutError, TimeoutError, ConnectionError, httpx.TransportError)
_SUMMARY_LIMIT = 500


@dataclass
class ToolRun:
    tool_call_id: str
    name: str
    ok: bool
    tool_message: ToolMessage
    status: str
    retry_count: int = 0
    duration_ms: int = 0


def validate_args(spec: ToolSpec, args: dict) -> str | None:
    """Validate tool arguments against JSON Schema; return an error string or None."""
    err = best_match(Draft202012Validator(spec.json_schema).iter_errors(args))
    if err is None:
        return None
    where = f"(field {err.json_path})" if err.json_path != "$" else ""
    return f"{err.message}{where}"


def _timeout_of(spec: ToolSpec) -> float:
    if spec.timeout is not None:
        return spec.timeout
    return settings.mcp_tool_timeout if spec.source == "mcp" else settings.tool_default_timeout


def _summarize(content: str) -> str:
    return content if len(content) <= _SUMMARY_LIMIT else content[:_SUMMARY_LIMIT] + "…(truncated)"


def _format_content(spec: ToolSpec, result) -> str:
    """Unwrap MCP text blocks, decode JSON where possible, and apply the registered result formatter."""
    if isinstance(result, list) and result and all(isinstance(b, dict) for b in result):
        texts = [b.get("text", "") for b in result if b.get("type") == "text"]
        if texts:
            result = "\n".join(texts)
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (json.JSONDecodeError, ValueError):
            return result
    if spec.format_result is not None and isinstance(result, dict):
        try:
            result = spec.format_result(result)
        except Exception:
            logger.exception("Result formatter failed; returning the original result: tool=%s", spec.name)
    return json.dumps(result, ensure_ascii=False, default=str)


def _cap_tokens(content: str) -> str:
    """Truncate tool results at line boundaries to fit the context budget. Audit summaries are independent."""
    limit = memory.tokens_to_chars(settings.tool_result_max_tokens)
    if len(content) <= limit:
        return content
    cut = content.rfind("\n", 0, limit)
    head = content[:cut if cut > limit // 2 else limit]
    return head + "\n…(Result truncated. Narrow the query to retrieve complete records.)"


async def _audit(conversation_id, tool_call_id, name, spec: ToolSpec | None, args,
                 result_summary, status, error_message, retry_count, duration_ms) -> None:


    logger.info("tool_run conv=%s tool=%s source=%s server=%s status=%s retry=%s duration_ms=%s%s",
                conversation_id or "-", name,
                spec.source if spec else "unknown",
                (spec.mcp_server if spec else None) or "-",
                status, retry_count, duration_ms,
                f" err={error_message[:80]!r}" if error_message else "")
    try:
        await repository.insert_tool_audit(
            conversation_id=conversation_id or None, tool_call_id=(tool_call_id or None) and tool_call_id[:64],
            tool_name=name[:128],
            tool_source=(spec.source if spec else "builtin"),
            mcp_server=(spec.mcp_server if spec else None),
            arguments=args or None, result_summary=result_summary, status=status,
            error_message=error_message and error_message[:500],
            retry_count=retry_count, duration_ms=duration_ms,
        )
    except Exception:
        logger.exception("Audit write failed; tool execution is unaffected: tool=%s status=%s", name, status)


async def _mcp_authorized(name, args, user_id):
    if not user_id:
        return False
    from app.business_store import owns_order
    if name in {"query_warranty", "query_return_status"}:
        return await owns_order(user_id, str(args.get("order_id", "")))
    if name == "query_logistics":
        from app.db.service_models import DemoOrder
        from sqlalchemy import select
        import app.db.base as db
        async with db.async_session() as s:
            return bool(await s.scalar(select(DemoOrder.order_id).where(
                DemoOrder.tracking_no == args.get("tracking_no"), DemoOrder.user_id == user_id)))
    return False  # Newly discovered MCP tools need an explicit ownership policy.


async def execute_tool_call(
    tool_call: dict, conversation_id: int, specs: dict[str, ToolSpec],
    *, confirmed: bool = False, deny_note: str | None = None, user_id: str = "",
) -> ToolRun:
    """Execute a tool through schema, ownership, confirmation, timeout, retry, and audit checks. Always return ToolRun. Only the interrupted graph can supply write confirmation."""
    name = tool_call.get("name") or ""
    tc_id = tool_call.get("id") or ""
    args = dict(tool_call.get("args") or {})
    started = time.monotonic()

    def _run(ok: bool, content: str, status: str, retry_count: int = 0) -> ToolRun:
        return ToolRun(tool_call_id=tc_id, name=name, ok=ok, status=status, retry_count=retry_count,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       tool_message=ToolMessage(content=content, tool_call_id=tc_id,
                                                name=name or "unknown",
                                                status="success" if ok else "error"))

    spec = specs.get(name)

    if spec is None:
        run = _run(False, f"Tool execution failed: unknown tool {name}", "failure")
        await _audit(conversation_id, tc_id, name or "unknown", None, args, None,
                     "failure", f"Unknown tool {name}", 0, run.duration_ms)
        return run


    try:
        verr = validate_args(spec, args)
    except Exception as e:  # noqa: BLE001
        logger.exception("Argument validator failed; check the external schema: tool=%s", name)
        run = _run(False, f"Tool unavailable: invalid argument schema ({type(e).__name__}). Explain the limitation to the user.", "failure")
        await _audit(conversation_id, tc_id, name, spec, args, None, "failure",
                     f"Invalid schema: {type(e).__name__}: {e}"[:500], 0, run.duration_ms)
        return run
    if verr is not None:
        run = _run(False, f"Argument validation failed: {verr}. Correct the arguments and retry. Ask the user for missing information; never invent it.",
                   "validation_blocked")
        await _audit(conversation_id, tc_id, name, spec, args, None, "validation_blocked", verr, 0, run.duration_ms)
        return run

    if spec.source == "mcp":
        try:
            authorized = await _mcp_authorized(name, args, user_id)
        except Exception:
            logger.exception("MCP ownership check failed: tool=%s", name)
            run = _run(False, "Identity verification is unavailable. Try again later or contact support.", "failure")
            await _audit(conversation_id, tc_id, name, spec, args, None,
                         "failure", "Business record ownership verification is unavailable", 0, run.duration_ms)
            return run
        if not authorized:
            run = _run(False, "No business records found for your account", "permission_denied")
            await _audit(conversation_id, tc_id, name, spec, args, None,
                         "permission_denied", "Business record ownership verification failed", 0, run.duration_ms)
            return run


    if spec.permission == "write" and not confirmed:
        note = deny_note or "This write requires user confirmation. Do not retry unless the user explicitly requests it."
        run = _run(False, f"{name} was not executed: {note}", "permission_denied")
        await _audit(conversation_id, tc_id, name, spec, args, None, "permission_denied",
                     note[:500], 0, run.duration_ms)
        return run


    if spec.inject_conversation:
        args["conversation_id"] = conversation_id
    if spec.inject_user_id:
        args["user_id"] = user_id
    if spec.permission == "write":
        retries = 0
    else:
        retries = settings.tool_max_retries if spec.max_retries is None else spec.max_retries
    tool_timeout = _timeout_of(spec)
    attempt = 0
    while True:
        try:
            result = await asyncio.wait_for(spec.tool.ainvoke(args), timeout=tool_timeout)
            content = _cap_tokens(_format_content(spec, result))
            run = _run(True, content, "success", attempt)
            await _audit(conversation_id, tc_id, name, spec, args, _summarize(content),
                         "success", None, attempt, run.duration_ms)
            return run
        except _TRANSIENT as e:
            if attempt < retries:
                attempt += 1
                logger.warning("Transient tool failure; retry %s: name=%s err=%s",
                               attempt, name, type(e).__name__)
                await asyncio.sleep(0.2 * attempt)
                continue
            is_timeout = isinstance(e, (asyncio.TimeoutError, TimeoutError))
            status = "timeout" if is_timeout else "failure"

            run = _run(False, f"Tool temporarily unavailable: {"Execution timed out" if is_timeout else type(e).__name__},"
                              "Try again later or explain the limitation to the user.", status, attempt)
            await _audit(conversation_id, tc_id, name, spec, args, None, status,
                         type(e).__name__, attempt, run.duration_ms)
            return run
        except Exception as e:
            logger.exception("Tool execution failed: name=%s", name)
            run = _run(False, f"Tool temporarily unavailable: {type(e).__name__}. Explain the limitation to the user; never invent results.",
                       "failure", attempt)
            await _audit(conversation_id, tc_id, name, spec, args, None, "failure",
                         f"{type(e).__name__}: {e}"[:500], attempt, run.duration_ms)
            return run
