from unittest.mock import AsyncMock
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graph import nodes
pytestmark = pytest.mark.usefixtures("business_db")


def test_agent_messages_injects_evidence_on_knowledge():
    msgs = nodes._agent_messages(
        {"route": "knowledge", "evidence": "[1] 退货: 7天",
         "messages": [HumanMessage("能退吗")]})

    assert isinstance(msgs[0], SystemMessage)
    assert "[1] 退货: 7天" not in msgs[0].content
    ctx = [m for m in msgs if isinstance(m, HumanMessage) and "[1] 退货: 7天" in m.content]
    assert len(ctx) == 1
    assert "query_faq" in ctx[0].content
    assert msgs[-2].content == "能退吗" and msgs[-1] is ctx[0]


def test_agent_messages_no_evidence_on_business():
    msgs = nodes._agent_messages({"route": "business", "messages": [HumanMessage("订单1001")]})
    assert isinstance(msgs[0], SystemMessage)
    assert all("已检索到的知识证据" not in (m.content or "") for m in msgs)


@pytest.fixture()
def builtin_only_specs(monkeypatch):

    from app.tools import registry

    async def only_builtin():
        return registry.builtin_specs()

    monkeypatch.setattr(nodes.registry, "get_all_specs", only_builtin)


@pytest.mark.asyncio
async def test_main_agent_accumulates_steps_and_tokens(monkeypatch, builtin_only_specs):
    ai = AIMessage("好的", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})

    class FakeModel:
        def bind_tools(self, tools):
            return self
        def bind(self, **kwargs):
            return self
        async def ainvoke(self, msgs, config=None):
            return ai

    monkeypatch.setattr(nodes, "get_chat_model", lambda **k: FakeModel())
    out = await nodes.main_agent({"messages": [HumanMessage("hi")], "steps": 1, "tokens_used": 100})
    assert out["steps"] == 2
    assert out["tokens_used"] == 115
    assert out["messages"][0] is ai


@pytest.mark.asyncio
async def test_agent_tools_executes_normal_tool(monkeypatch, builtin_only_specs):
    from langchain_core.messages import ToolMessage

    from app.tools.engine import ToolRun

    async def fake_exec(tc, cid, specs, **kw):
        return ToolRun(tool_call_id=tc["id"], name=tc["name"], ok=True, status="success",
                       tool_message=ToolMessage(content='{"status":"shipped"}',
                                                tool_call_id=tc["id"], name=tc["name"]))

    monkeypatch.setattr(nodes.engine, "execute_tool_call", fake_exec)
    ai = AIMessage("", tool_calls=[{"name": "query_logistics", "args": {"order_id": "1001"}, "id": "t1"}])
    out = await nodes.agent_tools({"messages": [ai], "conversation_id": 5})
    assert out["messages"][0].name == "query_logistics"
    assert not out.get("suggested_actions")


@pytest.mark.asyncio
async def test_agent_tools_create_ticket_missing_args_no_interrupt(monkeypatch, builtin_only_specs):

    from langchain_core.messages import ToolMessage

    from app.tools.engine import ToolRun

    seen = {}

    async def fake_exec(tc, cid, specs, **kw):
        seen["confirmed"] = kw.get("confirmed", False)
        return ToolRun(tool_call_id=tc["id"], name=tc["name"], ok=False, status="validation_blocked",
                       tool_message=ToolMessage(content="参数校验未通过:'description' is a required property",
                                                tool_call_id=tc["id"], name=tc["name"], status="error"))

    monkeypatch.setattr(nodes.engine, "execute_tool_call", fake_exec)
    ai = AIMessage("", tool_calls=[{"name": "create_ticket",
                    "args": {"ticket_type": "after_sales"}, "id": "t9"}])
    out = await nodes.agent_tools({"messages": [ai], "conversation_id": 5})
    assert not out.get("suggested_actions")
    assert seen["confirmed"] is False
    assert "参数校验未通过" in out["messages"][0].content


@pytest.mark.asyncio
async def test_agent_tools_still_intercepts_submit_refund(monkeypatch, builtin_only_specs):
    async def fake_exec(tc, cid, specs, **kw):
        raise AssertionError("submit_refund 不应进引擎(拦成前端退款表单)")

    monkeypatch.setattr(nodes.engine, "execute_tool_call", fake_exec)
    uid = "u-agent"
    mine = (await nodes.business.list_user_orders(uid))[0]["order_id"]
    ai = AIMessage("", tool_calls=[{"name": "submit_refund",
                    "args": {"order_id": mine}, "id": "t8"}])
    out = await nodes.agent_tools({"messages": [ai], "conversation_id": 5, "user_id": uid})
    assert out["suggested_actions"][0]["type"] == "refund_form"
    assert out["messages"][0].tool_call_id == "t8"


async def test_foreign_order_cannot_open_refund_form(monkeypatch, builtin_only_specs):


    async def fake_exec(tc, cid, specs, **kw):
        raise AssertionError("submit_refund 不应进引擎")

    monkeypatch.setattr(nodes.engine, "execute_tool_call", fake_exec)
    uid, other = "u-agent", "u-someone-else"

    his = [o["order_id"] for o in await nodes.business.list_user_orders(other)][0]
    ai = AIMessage("", tool_calls=[{"name": "submit_refund",
                    "args": {"order_id": his}, "id": "t9"}])
    out = await nodes.agent_tools({"messages": [ai], "conversation_id": 5, "user_id": uid})
    types = [a["type"] for a in out["suggested_actions"]]
    assert "refund_form" not in types
    assert "select_order" in types
    assert out["messages"][0].status == "error"
