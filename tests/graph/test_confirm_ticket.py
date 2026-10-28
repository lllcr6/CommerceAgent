import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph import nodes
from app.graph.build import build_graph
from app.graph.runtime import _graph_input
from app.tools import engine, registry


class FakeModel:

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def bind(self, **kw):
        return self

    async def ainvoke(self, msgs, config=None):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "create_ticket", "id": "tc-1",
                "args": {"description": "猫砂盆漏电", "ticket_type": "after_sales"}}])
        return AIMessage(content="已为您创建工单,请留意工单号。")


@pytest.fixture()
def wired(monkeypatch):
    async def fake_coref(q, h):
        return q

    async def fake_intent(q, h):
        return {"intent": "人工", "confidence": 0.95}

    monkeypatch.setattr(nodes.coref, "resolve", fake_coref)
    monkeypatch.setattr(nodes.intent_mod, "classify", fake_intent)
    model = FakeModel()
    monkeypatch.setattr(nodes, "get_chat_model", lambda **kw: model)

    async def only_builtin():
        return registry.builtin_specs()

    monkeypatch.setattr(nodes.registry, "get_all_specs", only_builtin)

    created, audits = [], []

    async def fake_create(cid, desc, ttype):
        created.append((cid, desc, ttype))
        return "T20260717001"

    async def fake_audit(**kw):
        audits.append(kw)


    monkeypatch.setattr("app.db.repository.create_ticket", fake_create)
    monkeypatch.setattr(engine.repository, "insert_tool_audit", fake_audit)

    async def no_msg(*a, **kw):
        return 1

    monkeypatch.setattr(nodes.repository, "append_message", no_msg)
    return created, audits


async def test_confirm_true_creates_ticket(wired):
    created, audits = wired
    g = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    st = await g.ainvoke(_graph_input("u1", "帮我建个工单,猫砂盆漏电", 1, 1, "", 0), cfg)
    intr = st["__interrupt__"][0].value
    assert intr["type"] == "confirm_ticket"
    assert intr["preview"] == {"ticket_type": "after_sales", "description": "猫砂盆漏电"}
    assert created == []

    st2 = await g.ainvoke(Command(resume={"confirmed": True}), cfg)
    assert created == [(1, "猫砂盆漏电", "after_sales")]
    assert any(a["status"] == "success" and a["tool_name"] == "create_ticket" for a in audits)
    assert "T20260717001" in str(st2["messages"])


async def test_confirm_false_denied_and_audited(wired):
    created, audits = wired
    g = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t2"}}
    await g.ainvoke(_graph_input("u1", "帮我建个工单,猫砂盆漏电", 1, 1, "", 0), cfg)
    st2 = await g.ainvoke(Command(resume={"confirmed": False}), cfg)
    assert created == []
    assert any(a["status"] == "permission_denied" and a["tool_name"] == "create_ticket" for a in audits)
    assert "cancelled" in str(st2["messages"])


async def test_missing_description_asks_instead_of_interrupt(wired, monkeypatch):

    class NoDescModel(FakeModel):
        async def ainvoke(self, msgs, config=None):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "create_ticket", "id": "tc-1", "args": {"ticket_type": "question"}}])
            return AIMessage(content="请问您遇到的具体问题是什么呢?")

    monkeypatch.setattr(nodes, "get_chat_model", lambda **kw: NoDescModel())
    created, audits = wired
    g = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t3"}}
    st = await g.ainvoke(_graph_input("u1", "帮我建个工单", 1, 1, "", 0), cfg)
    assert "__interrupt__" not in st
    assert created == [] and any(a["status"] == "validation_blocked" for a in audits)


async def test_multiple_create_ticket_only_first_confirmed(wired):

    class TwoTicketsModel(FakeModel):
        async def ainvoke(self, msgs, config=None):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "create_ticket", "id": "tc-1",
                     "args": {"description": "猫砂盆漏电", "ticket_type": "after_sales"}},
                    {"name": "create_ticket", "id": "tc-2",
                     "args": {"description": "重复请求", "ticket_type": "question"}}])
            return AIMessage(content="好的")

    created, audits = wired
    g = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t4"}}

    import app.graph.nodes as nodes_mod
    import pytest as _pytest
    model = TwoTicketsModel()
    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(nodes_mod, "get_chat_model", lambda **kw: model)
        st = await g.ainvoke(_graph_input("u1", "建两个工单", 1, 1, "", 0), cfg)
        assert st["__interrupt__"][0].value["preview"]["description"] == "猫砂盆漏电"
        st2 = await g.ainvoke(Command(resume={"confirmed": True}), cfg)
    assert created == [(1, "猫砂盆漏电", "after_sales")]
    assert "Only one ticket request" in str(st2["messages"])


async def test_resume_value_mismatch_treated_as_cancel(wired):

    created, audits = wired
    g = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t5"}}
    await g.ainvoke(_graph_input("u1", "帮我建个工单,猫砂盆漏电", 1, 1, "", 0), cfg)
    st2 = await g.ainvoke(Command(resume="1001"), cfg)
    assert created == []
    assert any(a["status"] == "permission_denied" for a in audits)
    assert "__interrupt__" not in st2
