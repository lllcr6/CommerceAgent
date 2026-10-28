import logging

from app.tools import registry


def test_builtin_scan_registers_core_tools_without_query_logistics():
    names = {s.name for s in registry.builtin_specs()}


    assert {"query_order", "query_product", "query_faq", "create_ticket", "submit_refund"} <= names
    assert "query_logistics" not in names


def test_every_spec_has_three_essentials():
    for s in registry.builtin_specs():
        assert s.name and s.description
        assert isinstance(s.json_schema, dict) and s.json_schema.get("properties") is not None


def test_permissions_only_trust_our_side():
    by = {s.name: s for s in registry.builtin_specs()}
    assert by["create_ticket"].permission == "write"
    assert all(s.permission == "read" for n, s in by.items() if n not in {"create_ticket", "request_human"})
    assert registry.permission_for("mcp_random_tool") == "read"


def test_create_ticket_schema_excludes_injected_conversation_id():
    spec = registry.get_builtin_spec("create_ticket")
    assert spec.inject_conversation is True
    assert "conversation_id" not in spec.json_schema.get("properties", {})


def test_query_faq_keeps_extended_timeout():
    assert registry.get_builtin_spec("query_faq").timeout == 30.0


def test_duplicate_register_is_dropped_with_warning(caplog):
    spec = registry.builtin_specs()[0]
    dup = registry.ToolSpec(name=spec.name, description="dup",
                            json_schema={"type": "object", "properties": {}},
                            tool=spec.tool, permission="read", source="builtin")
    with caplog.at_level(logging.WARNING):
        registry.register(dup)
    assert registry.get_builtin_spec(spec.name).description != "dup"
    assert any("Duplicate" in r.message for r in caplog.records)
