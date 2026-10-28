"""Knowledge gate must see authorized order facts before deciding to reject."""
import json
import pytest
from sqlalchemy import select
from langchain_core.messages import HumanMessage, AIMessage
from tests.test_service_security import service, new_conv
from app.graph import nodes, runtime
from app.db.models import ToolAuditLog
from app.db.service_models import DemoOrder

pytestmark=pytest.mark.asyncio

async def setup_policy(monkeypatch):
    seen={}
    async def understand(q):
        seen['retrieval_question']=q
        return {'standard':q,'expanded':[]}
    async def search(*a,**kw):
        return [{'id':1,'question':'退换货政策','answer':'符合条件且未拆封的商品可按退货政策申请。',
                 'rerank_score':.95,'section_path':'政策/退货','content_type':'policy','is_key_clause':True}]
    async def check(q,evidence):
        seen['check_question']=q;seen['check_evidence']=evidence
        return {'useful':True,'reason':'订单事实已提供，政策可按条件说明。'}
    monkeypatch.setattr(nodes.query_understanding,'understand',understand)
    monkeypatch.setattr(nodes.retrieval,'search_knowledge',search)
    monkeypatch.setattr(nodes.selfcheck,'check_sufficient',check)
    return seen

async def test_lookup_before_gate_and_agent_receives_order(service,monkeypatch):
    c,factory=service;cid=await new_conv(factory)
    seen=await setup_policy(monkeypatch)
    from app.graph.build import build_graph
    from langgraph.checkpoint.memory import InMemorySaver
    async def resolve(state):return {'resolved_query':'订单alice-1001的退换货政策是什么？'}
    async def classify(state):return {'intent':'product_policy','route':'knowledge'}
    async def agent(state,config=None):
        assert state['evidence_strong'] is True
        context=nodes._turn_context(state)
        assert 'query_order' in context and 'alice-1001' in context and 'Self-Cleaning Litter Box' in context
        assert 'Do not automatically request a refund' in context and 'missing' in context
        return {'messages':[AIMessage('这笔订单的商品是智能猫砂盆；退货需满足政策条件，是否已拆封？')],'steps':1}
    monkeypatch.setattr(nodes,'resolve_reference',resolve)
    monkeypatch.setattr(nodes,'classify_intent',classify)
    monkeypatch.setattr(nodes,'main_agent',agent)
    monkeypatch.setattr(runtime,'_graph',build_graph(InMemorySaver()))
    out=await runtime.run_turn('alice','【咨询订单：alice-1001】\n退换货政策是什么？',cid)
    state=out['state']
    assert state['order_data']['product']=='Self-Cleaning Litter Box Pro (MH-LP100)'
    assert 'Self-Cleaning Litter Box' in seen['retrieval_question'] and 'alice-1001' not in seen['retrieval_question']
    assert any('alice-1001' in text and 'Self-Cleaning Litter Box' in text for text in seen['check_evidence'])
    assert state['trace']['knowledge_order']['available'] is True
    async with factory() as s:
        logs=(await s.scalars(select(ToolAuditLog).where(ToolAuditLog.conversation_id==cid))).all()
        assert any(row.tool_name=='query_order' and row.status=='success' for row in logs)

async def test_cross_user_order_not_exposed_to_selfcheck(service,monkeypatch):
    c,factory=service;cid=await new_conv(factory)
    async with factory() as s:
        (await s.get(DemoOrder,'bob-1001')).product='BOB_PRIVATE_PRODUCT'
        await s.commit()
    seen=await setup_policy(monkeypatch)
    out=await nodes.retrieve_knowledge({'messages':[HumanMessage('【咨询订单：bob-1001】\n退货政策？')],
                                     'user_id':'alice','conversation_id':cid})
    assert out['order_data'].get('error') and 'BOB_PRIVATE_PRODUCT' not in json.dumps(out)
    assert 'BOB_PRIVATE_PRODUCT' not in str(seen['check_evidence'])
    assert out['trace']['knowledge_order']['available'] is False

async def test_generic_policy_does_not_force_order_selection(monkeypatch):
    seen=await setup_policy(monkeypatch)
    async def forbidden(*args,**kwargs):pytest.fail('generic policy needs no order lookup')
    monkeypatch.setattr(nodes.engine,'execute_tool_call',forbidden)
    out=await nodes.retrieve_knowledge({'messages':[HumanMessage('退货政策是什么？')],'user_id':'alice'})
    assert out['evidence_strong'] is True and 'order_data' not in out

async def test_context_refreshes_after_order_changes(service):
    c,factory=service;cid=await new_conv(factory)
    state={'messages':[HumanMessage('【咨询订单：alice-1001】\n退货政策？')],'user_id':'alice','conversation_id':cid}
    first=await nodes._knowledge_order_context(state)
    assert first['order_data']['status']=='paid'
    async with factory() as s:
        (await s.get(DemoOrder,'alice-1001')).status='shipped';await s.commit()
    second=await nodes._knowledge_order_context(state)
    assert second['order_data']['status']=='shipped'
    state['messages']=[HumanMessage('【咨询订单：alice-2002】\n退货政策？')]
    assert (await nodes._knowledge_order_context(state))['order_id']=='alice-2002'

async def test_missing_policy_still_blocks_generation(service,monkeypatch):
    c,factory=service;cid=await new_conv(factory)
    await setup_policy(monkeypatch)
    async def empty(*args,**kwargs):return []
    monkeypatch.setattr(nodes.retrieval,'search_knowledge',empty)
    out=await nodes.retrieve_knowledge({'messages':[HumanMessage('【咨询订单：alice-1001】\n退货政策？')],
                                     'user_id':'alice','conversation_id':cid})
    assert out['order_data']['order_id']=='alice-1001'
    assert out['evidence_strong'] is False and out['fallback_source']=='retrieval_low_conf'
