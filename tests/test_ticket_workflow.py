"""Ticket-only workflow with real sessions and persistence; no model services."""
import asyncio
import pytest
from sqlalchemy import select
from tests.test_service_security import service, new_conv
from app.db.models import Conversation, Message, Ticket
from app.db.service_models import TicketWorkflow, TicketEvent
from app.db.ticket_workflow import backfill_workflows

pytestmark = pytest.mark.asyncio

async def create(clients, factory, owner='alice', order=None):
    cid = await new_conv(factory, owner)
    payload = dict(conversation_id=cid, ticket_type='after_sales', description='请核实物流进度')
    if order:
        payload['order_id'] = order
    r = await clients[owner].post('/api/actions/create-ticket', json=payload)
    assert r.status_code == 200, r.text
    return cid, '/api/tickets/' + r.json()['ticket_no']

async def test_ticket_only_claim_public_private_and_complete(service):
    c, factory = service
    cid, path = await create(c, factory, order='alice-1001')
    assert (await c['alice'].get(f'/api/conversations/{cid}/service')).json()['state'] == 'ai'
    assert (await c['staff1'].get('/api/support/queue')).json()['items'] == []
    queue = (await c['staff1'].get('/api/tickets?scope=pending')).json()['items']
    assert len(queue) == 1 and queue[0]['version'] == 1
    d = (await c['staff1'].get(path)).json()
    assert not d['messages'] and d['order'] is None
    for who in ['alice', 'bob', 'anonymous']:
        assert (await c[who].post(path+'/claim', json={'version':1})).status_code in (401,403)
    r = await c['staff1'].post(path+'/claim',json={'version':1})
    assert r.status_code == 200, r.text
    assert (await c['staff2'].post(path+'/claim',json={'version':1})).status_code == 409
    assert (await c['staff2'].get(path)).status_code == 404
    assert len((await c['staff1'].get('/api/tickets?scope=mine')).json()['items']) == 1
    assert (await c['staff1'].get(f'/api/conversations/{cid}/messages')).status_code == 404
    assert (await c['staff1'].post(f'/api/support/{cid}/reply',json={'message':'越权回复'})).status_code == 404
    assert (await c['staff1'].get(path)).json()['order']['order_id'] == 'alice-1001'
    assert (await c['staff1'].post(path+'/records',json={'version':2,'content':'内部调查','visibility':'internal'})).status_code == 200
    assert (await c['staff1'].post(path+'/records',json={'version':2,'content':'过期提交'})).status_code == 409
    assert (await c['staff1'].post(path+'/records',json={'version':3,'content':'已联系仓库核实','visibility':'public'})).status_code == 200
    user = (await c['alice'].get(path)).json()
    assert '内部调查' not in str(user)
    assert '已联系仓库核实' in str(user)
    assert '内部调查' in str((await c['boss'].get(path)).json())
    for payload in [{'version':4}, {'version':4,'resolution':'  '}]:
        assert (await c['staff1'].post(path+'/complete',json=payload)).status_code == 422
    assert (await c['staff1'].patch(path)).status_code == 422
    assert (await c['boss'].post(path+'/complete',json={'version':4,'resolution':'绕过经办人'})).status_code == 403
    assert (await c['staff1'].post(path+'/complete',json={'version':4,'resolution':'仓库已补发，明日送达。'})).status_code == 200
    user = (await c['alice'].get(path)).json()
    assert user['state'] == 'completed' and user['resolution'] == '仓库已补发，明日送达。'
    assert user['completed_at'] and not user['can_manage']
    assert (await c['staff1'].post(path+'/records',json={'version':5,'content':'事后修改'})).status_code == 409
    assert (await c['boss'].post(path+'/assign',json={'version':5,'assignee_id':'staff2'})).status_code == 409
    assert (await c['alice'].get(f'/api/conversations/{cid}/service')).json()['state'] == 'ai'

async def test_assignment_reassignment_and_cross_user_security(service):
    c, factory = service
    cid,path = await create(c,factory,'bob')
    assert (await c['alice'].get(path)).status_code == 404
    assert (await c['alice'].get('/api/tickets')).json()['items'] == []
    assert (await c['alice'].get('/api/tickets?scope=all')).status_code == 403
    assert (await c['staff1'].get('/api/tickets?scope=all')).status_code == 403
    assert (await c['staff1'].get('/api/tickets/assignees')).status_code == 403
    assert (await c['boss'].post(path+'/assign',json={'version':1,'assignee_id':'bob'})).status_code == 400
    assert (await c['staff1'].post(path+'/assign',json={'version':1,'assignee_id':'staff1'})).status_code == 403
    assert (await c['boss'].post(path+'/assign',json={'version':1,'assignee_id':'staff1','reason':'初次分配'})).status_code == 200
    assert (await c['boss'].post(path+'/assign',json={'version':1,'assignee_id':'staff2'})).status_code == 409
    assert (await c['staff1'].post(path+'/records',json={'version':2,'content':'保留处理轨迹'})).status_code == 200
    assert (await c['boss'].post(path+'/assign',json={'version':3,'assignee_id':'staff2','reason':'交班'})).status_code == 200
    assert (await c['staff1'].get(path)).status_code == 404
    assert (await c['staff1'].post(path+'/records',json={'version':4,'content':'旧经办人写入'})).status_code == 404
    assert '保留处理轨迹' in str((await c['staff2'].get(path)).json())
    for suffix,payload in [('/records',{'version':4,'content':'伪造'}),('/complete',{'version':4,'resolution':'伪造'}),('/assign',{'version':4,'assignee_id':'alice'})]:
        assert (await c['alice'].post(path+suffix,json=payload)).status_code == 403
    assert (await c['alice'].patch(path+'/order',json={'version':4,'order_id':'alice-1001'})).status_code == 403
    assert (await c['staff2'].get('/api/tickets?conversation_id='+str(cid))).status_code == 404
    assert '交班' not in str((await c['bob'].get(path)).json())

async def test_ticket_order_scope_and_closed_conversation(service):
    c,factory=service
    cid=await new_conv(factory)
    bad=await c['alice'].post('/api/actions/create-ticket',json={'conversation_id':cid,'ticket_type':'after_sales','description':'无权订单','order_id':'bob-1001'})
    assert bad.status_code == 404
    assert (await c['alice'].get('/api/tickets')).json()['items'] == []
    cid,path=await create(c,factory)
    await c['staff1'].post(path+'/claim',json={'version':1})
    assert (await c['staff1'].patch(path+'/order',json={'version':2,'order_id':'bob-1001'})).status_code == 404
    assert (await c['staff1'].patch(path+'/order',json={'version':2,'order_id':'alice-1001'})).status_code == 200
    async with factory() as s:
        (await s.get(Conversation,cid)).status='closed'
        await s.commit()
    assert (await c['staff1'].get(f'/api/support/{cid}/orders')).status_code == 404
    payload={'version':1,'status':'shipped','status_code':'IN_TRANSIT','city':'杭州','description':'已从杭州分拨中心发出'}
    assert (await c['staff1'].patch(path+'/orders/alice-1002',json=payload)).status_code == 404
    assert (await c['staff1'].patch(path+'/orders/bob-1001',json=payload)).status_code == 404
    assert (await c['staff2'].patch(path+'/orders/alice-1001',json=payload)).status_code == 404
    r=await c['staff1'].patch(path+'/orders/alice-1001',json=payload)
    assert r.status_code == 200,r.text
    assert (await c['staff1'].patch(path+'/orders/alice-1001',json=payload)).status_code == 409
    from mcp_servers.logistics_server import query_logistics
    result=await query_logistics('DEMO-US-alice-1001')
    assert result['current_city']=='杭州' and result['status_code']=='IN_TRANSIT'
    assert (await c['alice'].get(path)).json()['order']['status']=='shipped'
    assert (await c['staff1'].post(path+'/complete',json={'version':4,'resolution':'物流已更新，请查收。'})).status_code == 200
    assert (await c['staff1'].patch(path+'/orders/alice-1001',json={'version':2,'status':'delivered'})).status_code == 409

async def test_concurrent_claim_has_one_winner(service):
    c,factory=service
    _,path=await create(c,factory)
    results=await asyncio.gather(*(c[n].post(path+'/claim',json={'version':1}) for n in ['staff1','staff2']))
    assert sorted(r.status_code for r in results)==[200,409]
    async with factory() as s:
        events=(await s.scalars(select(TicketEvent).where(TicketEvent.action=='claimed'))).all()
        assert len(events)==1

async def test_backfill_is_additive_and_idempotent(service):
    c,factory=service
    cid=await new_conv(factory)
    async with factory() as s:
        s.add_all([Ticket(ticket_no='legacy-open',conversation_id=cid,description='旧工单',ticket_type='question',status='pending'),Ticket(ticket_no='legacy-done',conversation_id=cid,description='旧已完成',ticket_type='question',status='completed')])
        await s.commit()
        await backfill_workflows(s)
        await s.commit()
        assert (await s.get(TicketWorkflow,'legacy-open')).state=='pending'
        assert (await s.get(TicketWorkflow,'legacy-done')).state=='completed'
    await c['staff1'].post('/api/tickets/legacy-open/claim',json={'version':1})
    async with factory() as s:
        await backfill_workflows(s)
        await s.commit()
        w=await s.get(TicketWorkflow,'legacy-open')
        assert w.assignee_id=='staff1' and w.state=='processing' and w.version==2

async def test_refund_ticket_automatically_links_owned_order(service):
    c,factory=service
    cid=await new_conv(factory)
    r=await c['alice'].post('/api/actions/create-refund',json={'conversation_id':cid,'order_id':'alice-1001','reason':'defective_item'})
    assert r.status_code==200,r.text
    number=r.json()['ticket_no']
    d=(await c['alice'].get('/api/tickets/'+number)).json()
    assert d['ticket_type']=='refund' and d['order_id']=='alice-1001' and d['state']=='pending'
    assert (await c['alice'].get(f'/api/conversations/{cid}/service')).json()['state']=='ai'
    assert any(t['ticket_no']==number for t in (await c['staff1'].get('/api/tickets?scope=pending')).json()['items'])
