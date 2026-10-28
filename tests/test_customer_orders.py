"""Orders are discovered from the signed-in account and carried into support flows."""
import pytest
from sqlalchemy import select,func
from tests.test_service_security import service
from app.db.models import Conversation,Ticket,Message
from app.db.service_models import TicketWorkflow
pytestmark=pytest.mark.asyncio

async def test_order_details_and_tickets_are_owner_scoped(service):
    c,factory=service
    orders=(await c['alice'].get('/api/orders')).json()['items']
    assert len(orders)==2 and all(o['user_id']=='alice' for o in orders)
    path='/api/orders/alice-1001'
    d=(await c['alice'].get(path)).json()
    assert d['order']['order_id']=='alice-1001' and d['events'][0]['status_code']=='PICKED_UP'
    for who in ['bob','staff1','boss']:
        expected = 404 if who == 'bob' else 403
        assert (await c[who].get(path)).status_code==expected
        assert (await c[who].post(path+'/tickets',json={'description':'偷看订单'})).status_code==expected
    assert (await c['anonymous'].get(path)).status_code==401
    assert (await c['anonymous'].post(path+'/tickets',json={'description':'未登录'})).status_code==401
    assert (await c['alice'].post('/api/orders/bob-1001/tickets',json={'description':'越权'})).status_code==404
    assert (await c['alice'].post(path+'/tickets',json={'description':'   '})).status_code==422
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(Conversation))==0
    r=await c['alice'].post(path+'/tickets',json={'ticket_type':'after_sales','description':'订单没有发货，请核实。','user_id':'bob'})
    assert r.status_code==200,r.text
    d=r.json()
    async with factory() as s:
        assert (await s.get(Conversation,d['conversation_id'])).user_id=='alice'
        assert (await s.get(TicketWorkflow,d['ticket_no'])).order_id=='alice-1001'
        assert (await s.get(Ticket,d['ticket_no'])).description=='订单没有发货，请核实。'
    assert (await c['alice'].get(f"/api/conversations/{d['conversation_id']}/service")).json()['state']=='ai'
    assert any(t['ticket_no']==d['ticket_no'] for t in (await c['staff1'].get('/api/tickets?scope=pending')).json()['items'])

async def test_chat_order_context_validated_before_conversation_creation(service,monkeypatch):
    c,factory=service
    from app.graph import runtime
    seen=[]
    async def stream(uid,message,cid):
        seen.append((uid,message,cid))
        yield {'type':'done','conversation_id':cid}
    monkeypatch.setattr(runtime,'stream_turn',stream)
    assert (await c['alice'].post('/api/chat',json={'message':'查物流','order_id':'bob-1001'})).status_code==404
    assert seen==[]
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(Conversation))==0
    r=await c['alice'].post('/api/chat',json={'message':'什么时候发货？','order_id':'alice-1001','user_id':'bob'})
    assert r.status_code==200,r.text
    assert seen[0][0]=='alice' and seen[0][1]=='[Order: alice-1001]\n什么时候发货？'

async def test_order_page_reads_staff_updates(service):
    c,factory=service
    result=(await c['alice'].post('/api/orders/alice-1001/tickets',json={'description':'核实物流'})).json()
    path='/api/tickets/'+result['ticket_no']
    await c['staff1'].post(path+'/claim',json={'version':1})
    r=await c['staff1'].patch(path+'/orders/alice-1001',json={'version':1,'status':'shipped','return_code':'AUDITING','status_code':'IN_TRANSIT','city':'杭州','description':'杭州分拨中心发出'})
    assert r.status_code==200,r.text
    d=(await c['alice'].get('/api/orders/alice-1001')).json()
    assert d['order']['status']=='shipped' and d['order']['return_code']=='AUDITING'
    assert d['events'][0]['city']=='杭州' and d['events'][0]['description']=='杭州分拨中心发出'
    assert (await c['bob'].get('/api/orders/alice-1001')).status_code==404
