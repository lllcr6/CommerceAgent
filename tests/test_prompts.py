from langchain_core.messages import HumanMessage

from app.core.prompts import CUSTOMER_SERVICE_PROMPT, EXTRACT_PROMPT, AGENT_SYSTEM, AGENT_PROMPT


def test_customer_service_prompt_renders_with_history():
    msgs = CUSTOMER_SERVICE_PROMPT.format_messages(
        history=[HumanMessage("你们卖猫粮吗?")]
    )
    assert msgs[0].type == "system"
    assert msgs[-1].content == "你们卖猫粮吗?"

    for keyword in ("PawPal", "English", "orders"):
        assert keyword in msgs[0].content


def test_extract_prompt_renders_text():
    msgs = EXTRACT_PROMPT.format_messages(text="订单 MH1 坏了要退款")
    assert msgs[0].type == "system"
    assert "订单 MH1 坏了要退款" in msgs[-1].content


def test_agent_system_covers_tool_principles():
    for kw in ["PawPal", "tools", "query_faq", "create_ticket", "Do not guess"]:
        assert kw in AGENT_SYSTEM


def test_agent_prompt_has_history_placeholder():
    assert any(getattr(m, "variable_name", None) == "history"
               for m in AGENT_PROMPT.messages)
