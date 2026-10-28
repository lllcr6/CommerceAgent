import asyncio

import pytest

from app.tools import engine
from app.tools.registry import ToolSpec

SCHEMA = {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}
TICKET_SCHEMA = {"type": "object", "properties": {"description": {"type": "string"}},
                 "required": ["description"]}


def _spec(name="query_order", *, permission="read", source="builtin", tool=None,
          schema=SCHEMA, timeout=None, inject=False, inject_user=False, fmt=None):
    return ToolSpec(name=name, description="测试工具", json_schema=schema, tool=tool,
                    permission=permission, source=source, timeout=timeout,
                    inject_conversation=inject, inject_user_id=inject_user, format_result=fmt)


def _tool(fn, name="query_order"):
    return type("T", (), {"name": name, "ainvoke": staticmethod(fn)})()


@pytest.fixture()
def audits(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(engine, "_mcp_authorized", AsyncMock(return_value=True))
    rows: list[dict] = []

    async def fake_audit(**kw):
        rows.append(kw)

    monkeypatch.setattr(engine.repository, "insert_tool_audit", fake_audit)
    return rows


async def test_unknown_tool(audits):
    run = await engine.execute_tool_call({"name": "nope", "args": {}, "id": "c1"}, 1, {})
    assert run.ok is False and "unknown tool" in run.tool_message.content
    assert audits[-1]["status"] == "failure"


async def test_malformed_tool_call_never_raises(audits):
    run = await engine.execute_tool_call({"args": {}}, 1, {})
    assert run.ok is False


async def test_validation_blocks_and_feeds_back(audits):
    async def boom(_args):
        raise AssertionError("校验不过不许执行")
    spec = _spec(tool=_tool(boom))
    run = await engine.execute_tool_call({"name": "query_order", "args": {}, "id": "c1"}, 1,
                                         {"query_order": spec})
    assert run.ok is False and run.status == "validation_blocked"
    assert "Argument validation failed" in run.tool_message.content and run.tool_message.status == "error"
    assert audits[-1]["status"] == "validation_blocked" and audits[-1]["retry_count"] == 0


async def test_write_without_confirmation_denied(audits):
    async def boom(_args):
        raise AssertionError("未确认不许执行")
    spec = _spec("create_ticket", permission="write", tool=_tool(boom, "create_ticket"),
                 schema=TICKET_SCHEMA)
    run = await engine.execute_tool_call({"name": "create_ticket", "args": {"description": "x"}, "id": "c1"},
                                         1, {"create_ticket": spec})
    assert run.ok is False and run.status == "permission_denied"
    assert audits[-1]["status"] == "permission_denied"


async def test_write_confirmed_executes_and_not_retried(audits):
    calls = {"n": 0}

    async def flaky(_args):
        calls["n"] += 1
        raise RuntimeError("boom")
    spec = _spec("create_ticket", permission="write", tool=_tool(flaky, "create_ticket"),
                 schema=TICKET_SCHEMA)
    run = await engine.execute_tool_call({"name": "create_ticket", "args": {"description": "x"}, "id": "c1"},
                                         1, {"create_ticket": spec}, confirmed=True)
    assert run.ok is False and calls["n"] == 1 and run.retry_count == 0


async def test_transient_timeout_retries_then_gives_up(audits):
    async def slow(_args):
        await asyncio.sleep(1)
    spec = _spec(tool=_tool(slow), timeout=0.05)
    run = await engine.execute_tool_call({"name": "query_order", "args": {"order_id": "1"}, "id": "c1"},
                                         1, {"query_order": spec})
    assert run.ok is False and run.status == "timeout"
    assert run.retry_count == 2
    assert audits[-1]["status"] == "timeout" and audits[-1]["retry_count"] == 2
    assert audits[-1]["duration_ms"] is not None


async def test_business_error_not_retried(audits):
    calls = {"n": 0}

    async def fail(_args):
        calls["n"] += 1
        raise ValueError("业务错")
    spec = _spec(tool=_tool(fail))
    run = await engine.execute_tool_call({"name": "query_order", "args": {"order_id": "1"}, "id": "c1"},
                                         1, {"query_order": spec})
    assert run.ok is False and calls["n"] == 1 and "Tool temporarily unavailable" in run.tool_message.content


async def test_retry_succeeds_second_attempt(audits):
    calls = {"n": 0}

    async def flaky(_args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("网络抖动")
        return {"order_id": "1", "status": "shipped"}
    spec = _spec(tool=_tool(flaky))
    run = await engine.execute_tool_call({"name": "query_order", "args": {"order_id": "1"}, "id": "c1"},
                                         1, {"query_order": spec})
    assert run.ok is True and calls["n"] == 2 and run.retry_count == 1
    assert "shipped" in run.tool_message.content
    assert audits[-1]["status"] == "success" and audits[-1]["retry_count"] == 1


async def test_format_result_hook_translates_enum(audits):
    async def ok(_args):
        return {"tracking_no": "SF1", "status_code": "IN_TRANSIT", "internal_ref": "x9"}

    def fmt(d):
        return {"tracking_no": d["tracking_no"],
                "status": {"IN_TRANSIT": "运输中"}.get(d.get("status_code"), d.get("status_code"))}
    spec = _spec("query_logistics", source="mcp", tool=_tool(ok, "query_logistics"),
                 schema={"type": "object", "properties": {"tracking_no": {"type": "string"}},
                         "required": ["tracking_no"]}, fmt=fmt)
    run = await engine.execute_tool_call({"name": "query_logistics", "args": {"tracking_no": "SF1"}, "id": "c1"},
                                         1, {"query_logistics": spec})
    assert "运输中" in run.tool_message.content and "internal_ref" not in run.tool_message.content
    assert audits[-1]["tool_source"] == "mcp"


async def test_mcp_str_result_parsed_then_formatted(audits):
    async def ok(_args):
        return '{"tracking_no": "SF1", "status_code": "IN_TRANSIT"}'

    def fmt(d):
        return {"status": {"IN_TRANSIT": "运输中"}.get(d.get("status_code"))}
    spec = _spec("query_logistics", source="mcp", tool=_tool(ok, "query_logistics"),
                 schema={"type": "object", "properties": {"tracking_no": {"type": "string"}},
                         "required": ["tracking_no"]}, fmt=fmt)
    run = await engine.execute_tool_call({"name": "query_logistics", "args": {"tracking_no": "SF1"}, "id": "c1"},
                                         1, {"query_logistics": spec})
    assert run.ok and "运输中" in run.tool_message.content


async def test_mcp_content_blocks_unwrapped(audits):
    async def ok(_args):

        return [{"type": "text", "text": '{"status_code": "DELIVERED"}', "id": "lc_random"}]

    def fmt(d):
        return {"status": {"DELIVERED": "delivered"}.get(d.get("status_code"))}
    spec = _spec("query_logistics", source="mcp", tool=_tool(ok, "query_logistics"),
                 schema={"type": "object", "properties": {"tracking_no": {"type": "string"}},
                         "required": ["tracking_no"]}, fmt=fmt)
    run = await engine.execute_tool_call({"name": "query_logistics", "args": {"tracking_no": "SF1"}, "id": "c1"},
                                         1, {"query_logistics": spec})
    assert run.ok and "delivered" in run.tool_message.content and "lc_random" not in run.tool_message.content


async def test_malformed_external_schema_never_raises(audits):

    async def ok(_args):
        return {"x": 1}
    bad_schema = {"type": "object", "properties": {"x": {"type": "strin"}}, "required": ["x"]}
    spec = _spec("ext_tool", source="mcp", tool=_tool(ok, "ext_tool"), schema=bad_schema)
    run = await engine.execute_tool_call({"name": "ext_tool", "args": {"x": "1"}, "id": "c1"},
                                         1, {"ext_tool": spec})
    assert run.ok is False and run.status == "failure" and "invalid argument schema" in run.tool_message.content
    assert audits[-1]["status"] == "failure"


async def test_audit_fields_clamped_to_ddl_width(audits):

    spec = _spec(schema={"type": "object", "properties": {"order_id": {"type": "string", "maxLength": 3}},
                         "required": ["order_id"]})
    await engine.execute_tool_call({"name": "query_order", "args": {"order_id": "长" * 2000}, "id": "c1"},
                                   1, {"query_order": spec})
    assert audits[-1]["status"] == "validation_blocked" and len(audits[-1]["error_message"]) <= 500
    await engine.execute_tool_call({"name": "编" * 300, "args": {}, "id": "c2"}, 1, {})
    assert len(audits[-1]["tool_name"]) <= 128


async def test_spec_max_retries_zero_disables_retry(audits):

    calls = {"n": 0}

    async def slow(_args):
        calls["n"] += 1
        await asyncio.sleep(1)
    spec = _spec("query_faq", tool=_tool(slow, "query_faq"), timeout=0.05,
                 schema={"type": "object", "properties": {}})
    spec.max_retries = 0
    run = await engine.execute_tool_call({"name": "query_faq", "args": {}, "id": "c1"},
                                         1, {"query_faq": spec})
    assert run.ok is False and calls["n"] == 1 and run.retry_count == 0


async def test_formatter_exception_degrades_to_raw(audits):

    async def ok(_args):
        return {"tracking_no": "SF1"}

    def bad_fmt(d):
        raise KeyError("status_code")
    spec = _spec("query_logistics", source="mcp", tool=_tool(ok, "query_logistics"),
                 schema={"type": "object", "properties": {"tracking_no": {"type": "string"}},
                         "required": ["tracking_no"]}, fmt=bad_fmt)
    run = await engine.execute_tool_call({"name": "query_logistics", "args": {"tracking_no": "SF1"}, "id": "c1"},
                                         1, {"query_logistics": spec})
    assert run.ok is True and "SF1" in run.tool_message.content
    assert audits[-1]["status"] == "success"


async def test_audit_failure_never_blocks_execution(monkeypatch):
    async def audit_boom(*a, **kw):
        raise RuntimeError("审计库挂了")
    monkeypatch.setattr(engine.repository, "insert_tool_audit", audit_boom)

    async def ok(_args):
        return {"order_id": "1"}
    spec = _spec(tool=_tool(ok))
    run = await engine.execute_tool_call({"name": "query_order", "args": {"order_id": "1"}, "id": "c1"},
                                         1, {"query_order": spec})
    assert run.ok is True


async def test_inject_conversation_after_validation(audits):
    seen = {}

    async def ok(args):
        seen.update(args)
        return {"ticket_no": "T1"}
    schema = {"type": "object", "properties": {"description": {"type": "string"}},
              "required": ["description"], "additionalProperties": False}
    spec = _spec("create_ticket", permission="write", tool=_tool(ok, "create_ticket"),
                 schema=schema, inject=True)
    run = await engine.execute_tool_call({"name": "create_ticket", "args": {"description": "x"}, "id": "c1"},
                                         7, {"create_ticket": spec}, confirmed=True)
    assert run.ok is True and seen.get("conversation_id") == 7


async def test_inject_user_id_after_validation(audits):

    seen = {}

    async def ok(args):
        seen.update(args)
        return {"order_id": args["order_id"]}
    spec = _spec(tool=_tool(ok), inject_user=True)
    run = await engine.execute_tool_call({"name": "query_order", "args": {"order_id": "1001"}, "id": "c1"},
                                         7, {"query_order": spec}, user_id="u-real")
    assert run.ok is True and seen.get("user_id") == "u-real"


async def test_injected_identity_overrides_model_arguments(audits):


    seen = {}

    async def ok(args):
        seen.update(args)
        return {"order_id": args["order_id"]}
    schema = {"type": "object",
              "properties": {"order_id": {"type": "string"}, "user_id": {"type": "string"}},
              "required": ["order_id"]}
    spec = _spec(tool=_tool(ok), schema=schema, inject_user=True)
    run = await engine.execute_tool_call(
        {"name": "query_order", "args": {"order_id": "1001", "user_id": "u-victim"}, "id": "c1"},
        7, {"query_order": spec}, user_id="u-real")
    assert run.ok is True
    assert seen.get("user_id") == "u-real"


async def test_tools_without_injection_receive_no_identity_arguments(audits):
    seen = {}

    async def ok(args):
        seen.update(args)
        return {"ok": True}
    spec = _spec(tool=_tool(ok))                 # inject_user=False
    await engine.execute_tool_call({"name": "query_order", "args": {"order_id": "1001"}, "id": "c1"},
                                   7, {"query_order": spec}, user_id="u-real")
    assert "user_id" not in seen


async def test_result_summary_truncated_in_audit(audits):
    async def ok(_args):
        return {"blob": "长" * 1000}
    spec = _spec(tool=_tool(ok))
    await engine.execute_tool_call({"name": "query_order", "args": {"order_id": "1"}, "id": "c1"},
                                   1, {"query_order": spec})
    assert len(audits[-1]["result_summary"]) <= 520 and "truncated" in audits[-1]["result_summary"]
