"""Three roles are separate capabilities, including direct page/API access."""
import pytest
from tests.test_service_security import service, new_conv
from app.db.service_models import TicketWorkflow
from app.db.models import Conversation
pytestmark = pytest.mark.asyncio

async def test_pages_and_static_html_follow_role_home(service):
    c, _ = service
    homes = {'alice':'/', 'staff1':'/support', 'boss':'/admin'}
    groups = {'alice':['/','/orders','/static/index.html','/static/orders.html'],
              'staff1':['/support','/static/support.html'],
              'boss':['/admin','/kb','/rag-eval','/review','/observability','/topics','/topics/questions',
                      '/acceptance','/acceptance/eval','/acceptance/data','/acceptance/errors',
                      '/static/admin.html','/static/kb.html','/static/rageval.html','/static/review.html',
                      '/static/observability.html','/static/topics.html','/static/topic-questions.html',
                      '/static/acceptance.html','/static/acceptance-eval.html','/static/acceptance-data.html','/static/acceptance-errors.html']}
    for owner, paths in groups.items():
        for path in paths:
            for role, home in homes.items():
                r = await c[role].get(path)
                assert r.status_code == (200 if role == owner else 303), (role,path,r.text)
                if role != owner: assert r.headers['location'] == home
            r = await c['anonymous'].get(path)
            assert r.status_code == 303 and r.headers['location'] == '/login'
    for role in homes:
        assert (await c[role].get('/tickets')).status_code == 200

async def test_only_users_can_start_or_modify_user_flows(service):
    c, factory = service
    cid = await new_conv(factory)
    operations = [
        ('POST','/api/chat',{'message':'你好'}),
        ('POST','/api/agent',{'message':'你好'}),
        ('GET','/api/orders',None), ('GET','/api/orders/alice-1001',None),
        ('POST','/api/orders/alice-1001/tickets',{'description':'请协助'}),
        ('GET','/api/conversations',None),
        ('GET',f'/api/conversations/{cid}/generation',None),
        ('GET',f'/api/conversations/{cid}/generation/events?run_id=test',None),
        ('POST','/api/actions/transfer-human',{'conversation_id':cid}),
        ('POST',f'/api/conversations/{cid}/human-messages',{'message':'你好'}),
        ('POST',f'/api/conversations/{cid}/rating',{'rating':'satisfied'}),
        ('POST','/api/actions/create-ticket',{'conversation_id':cid,'description':'帮助','ticket_type':'question'}),
        ('POST','/api/actions/create-refund',{'conversation_id':cid,'order_id':'alice-1001','reason':'defective_item'}),
        ('POST','/api/actions/resume',{'conversation_id':cid,'confirmed':True}),
        ('POST','/api/feedback',{'conversation_id':cid,'question':'问题','rating':'up'}),
    ]
    for name in ['staff1','boss']:
        for method,path,body in operations:
            r = await c[name].request(method,path,json=body)
            assert r.status_code == 403, (name,path,r.text)

async def test_support_operations_exclude_admin_and_users(service):
    c,factory = service
    cid = await new_conv(factory)
    assert (await c['alice'].post('/api/actions/transfer-human',json={'conversation_id':cid})).status_code == 200
    for who in ['alice','boss']:
        for method,path,body in [('GET','/api/support/queue',None),('GET','/api/support/mine',None),
                                ('POST',f'/api/support/{cid}/claim',None),
                                ('POST',f'/api/support/{cid}/reply',{'message':'代回复'}),
                                ('POST',f'/api/support/{cid}/close',None),
                                ('GET',f'/api/support/{cid}/orders',None),
                                ('PATCH',f'/api/support/{cid}/orders/alice-1001',{'version':1,'status':'shipped'})]:
            r=await c[who].request(method,path,json=body)
            assert r.status_code == 403,(who,path,r.text)
    assert (await c['staff1'].post(f'/api/support/{cid}/claim')).status_code == 200
    assert (await c['staff1'].post(f'/api/support/{cid}/reply',json={'message':'客服回复'})).status_code == 200
    for who in ['alice','staff1']:
        assert (await c[who].get('/api/jobs')).status_code == 403

async def test_admin_supervises_and_assigns_but_never_processes(service):
    c,factory=service
    cid=await new_conv(factory)
    made=await c['alice'].post('/api/actions/create-ticket',json={'conversation_id':cid,'description':'协助订单','ticket_type':'question','order_id':'alice-1001'})
    path='/api/tickets/'+made.json()['ticket_no']
    targets=(await c['boss'].get('/api/tickets/assignees')).json()['items']
    assert {t['id'] for t in targets}=={'staff1','staff2'}
    data=(await c['boss'].get(path)).json()
    assert data['can_assign'] and not data['can_claim'] and not data['can_manage']
    assert (await c['boss'].post(path+'/assign',json={'version':1,'assignee_id':'boss'})).status_code==400
    assert (await c['boss'].post(path+'/assign',json={'version':1,'assignee_id':'staff1'})).status_code==200
    for method,suffix,body in [('POST','/claim',{'version':2}),('POST','/records',{'version':2,'content':'代处理'}),
                               ('POST','/complete',{'version':2,'resolution':'代完成'}),('PATCH','',{'version':2,'resolution':'旧接口'}),
                               ('PATCH','/order',{'version':2,'order_id':'alice-1001'}),
                               ('PATCH','/orders/alice-1001',{'version':1,'status':'shipped'})]:
        assert (await c['boss'].request(method,path+suffix,json=body)).status_code==403
    # Even legacy assignments to admins must not restore processing rights.
    async with factory() as s:
        (await s.get(TicketWorkflow,made.json()['ticket_no'])).assignee_id='boss'
        await s.commit()
    assert not (await c['boss'].get(path)).json()['can_manage']
    assert (await c['boss'].post(path+'/complete',json={'version':2,'resolution':'旧权限'})).status_code==403
    assert (await c['boss'].post(path+'/assign',json={'version':2,'assignee_id':'staff2'})).status_code==200

async def test_staff_cannot_use_legacy_user_conversation_ownership(service):
    c,factory=service
    async with factory() as s:
        conv=Conversation(user_id='staff1');s.add(conv);await s.commit();cid=conv.id
    assert (await c['staff1'].get(f'/api/conversations/{cid}/messages')).status_code==404
    assert (await c['staff1'].post('/api/actions/transfer-human',json={'conversation_id':cid})).status_code==403
