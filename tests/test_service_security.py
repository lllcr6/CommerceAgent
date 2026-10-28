"""Offline integration tests: real sessions, SQLite, production API routing, no model/Milvus."""
import asyncio
import pytest
import pytest_asyncio
import httpx
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import app.db.base as db
from app.db.models import Conversation, Message
from app.db.service_models import Account, LoginSession, HumanSession, BusinessAudit
from app.auth import password_hash
from app.business_store import seed_orders

@compiles(BigInteger, "sqlite")
def sqlite_bigint(element, compiler, **kw):
    return "INTEGER"

@pytest_asyncio.fixture
async def service(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/service.sqlite")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "async_session", factory)
    async with engine.begin() as c:
        await c.run_sync(db.Base.metadata.create_all)
    async with factory() as s:
        for uid, role in [("alice", "user"), ("bob", "user"), ("staff1", "support"), ("staff2", "support"), ("boss", "admin")]:
            s.add(Account(id=uid, role=role, password_hash=password_hash("password123")))
            await s.flush()
            if role == "user":
                await seed_orders(s, uid)
        await s.commit()
    from app.main import app
    clients = {}
    for name in ["alice", "bob", "staff1", "staff2", "boss", "anonymous"]:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients[name] = client
        if name != "anonymous":
            r = await client.post('/api/auth/login', json={"username": name, "password": "password123"})
            assert r.status_code == 200, r.text
    yield clients, factory
    for c in clients.values():
        await c.aclose()
    await engine.dispose()

async def new_conv(factory, uid='alice'):
    async with factory() as s:
        c = Conversation(user_id=uid)
        s.add(c)
        await s.commit()
        return c.id

@pytest.mark.asyncio
async def test_cross_user_reads_and_writes(service):
    clients, factory = service
    cid = await new_conv(factory, 'bob')
    a = clients['alice']
    before = await clients['bob'].get('/api/conversations')
    for path in [f'/api/conversations/{cid}/messages', f'/api/conversations/{cid}/service']:
        assert (await a.get(path)).status_code == 404
    payloads = {
        '/api/chat': {'user_id':'bob','conversation_id':cid,'message':'test'},
        '/api/agent': {'user_id':'bob','conversation_id':cid,'message':'test'},
        '/api/actions/resume': {'conversation_id':cid,'confirmed':True},
        '/api/actions/create-ticket': {'conversation_id':cid,'ticket_type':'question','description':'stolen'},
        '/api/actions/create-refund': {'conversation_id':cid,'order_id':'bob-1001','reason':'defective_item'},
        '/api/actions/transfer-human': {'conversation_id':cid},
        '/api/feedback': {'conversation_id':cid,'rating':'down','question':'stolen'},
        f'/api/conversations/{cid}/human-messages': {'message':'stolen'},
        f'/api/conversations/{cid}/rating': {'rating':'satisfied'},
    }
    for path, payload in payloads.items():
        r = await a.post(path, json=payload)
        assert r.status_code == 404, (path, r.text)
    assert (await a.get('/api/conversations?user_id=bob')).json()['items'] == []
    assert (await clients['bob'].get('/api/conversations')).json() == before.json()
    async with factory() as s:
        assert (await s.get(Conversation, cid)).status == 'active'
        assert (await s.scalars(select(Message))).all() == []

@pytest.mark.asyncio
async def test_identity_is_session_and_admin_is_protected(service, monkeypatch):
    clients, factory = service
    from app.graph import runtime
    seen = []
    async def stream(uid, message, cid):
        seen.append(uid)
        yield {'type':'done', 'conversation_id':cid}
    monkeypatch.setattr(runtime, 'stream_turn', stream)
    r = await clients['alice'].post('/api/chat', json={'user_id':'bob','message':'hello'})
    assert r.status_code == 200
    assert seen == ['alice']
    assert (await clients['alice'].get('/api/conversations')).json()['items'][0]['status'] == 'active'
    assert (await clients['bob'].get('/api/conversations')).json()['items'] == []
    for name in ['alice','staff1','anonymous']:
        expected = 401 if name == 'anonymous' else 403
        endpoints = [('GET','/api/admin/overview'), ('GET','/api/jobs'),
                     ('POST','/api/jobs/flywheel'), ('GET','/api/kb/overview'),
                     ('POST','/api/kb/search'), ('POST','/api/kb/ingest'),
                     ('GET','/api/review/queue'), ('POST','/api/review/1/approve'),
                     ('GET','/api/topics/distribution'), ('GET','/api/observability/overview'),
                     ('GET','/api/acceptance/overview'), ('POST','/api/acceptance/classify'),
                     ('GET','/api/rag-eval/overview'), ('POST','/api/extract')]
        for method,path in endpoints:
            r=await clients[name].request(method,path)
            assert r.status_code == expected, (name,method,path,r.text)
    assert (await clients['anonymous'].get('/api/conversations')).status_code == 401
    assert (await clients['alice'].get('/api/support/queue')).status_code == 403

@pytest.mark.asyncio
async def test_human_lifecycle_and_closed_guards(service, monkeypatch):
    clients, factory = service
    cid = await new_conv(factory)
    a, s1, s2 = (clients[n] for n in ['alice','staff1','staff2'])
    assert (await a.post(f'/api/conversations/{cid}/rating', json={'rating':'satisfied'})).status_code == 409
    assert (await a.post('/api/actions/transfer-human', json={'conversation_id':cid})).json()['state'] == 'queued'
    assert (await a.post('/api/actions/transfer-human', json={'conversation_id':cid})).json()['state'] == 'queued'
    assert len((await s1.get('/api/support/queue')).json()['items']) == 1
    assert (await s1.get(f'/api/conversations/{cid}/messages')).status_code == 404
    assert (await s1.post(f'/api/support/{cid}/claim')).status_code == 200
    assert (await s2.post(f'/api/support/{cid}/claim')).status_code == 409
    assert (await s2.post(f'/api/support/{cid}/reply', json={'message':'steal'})).status_code == 404
    assert (await s2.post(f'/api/support/{cid}/close')).status_code == 404
    from app.graph import runtime
    def forbidden_graph():
        pytest.fail('AI must not run while human is in control')
    monkeypatch.setattr(runtime, 'get_graph', forbidden_graph)
    for path in ['/api/chat','/api/agent']:
        assert (await a.post(path, json={'message':'hi','conversation_id':cid})).status_code == 409
    assert (await a.post('/api/actions/resume', json={'conversation_id':cid,'confirmed':True})).status_code == 409
    assert (await a.post(f'/api/conversations/{cid}/human-messages', json={'message':'hello human'})).status_code == 200
    assert (await s1.post(f'/api/support/{cid}/reply', json={'message':'hello customer'})).status_code == 200
    messages = (await a.get(f'/api/conversations/{cid}/messages')).json()['items']
    assert [m['content'] for m in messages] == ['hello human','hello customer']
    assert (await s1.post(f'/api/support/{cid}/close')).status_code == 200
    for path, payload in [(f'/api/conversations/{cid}/human-messages', {'message':'continue'}),('/api/chat',{'message':'continue','conversation_id':cid}),('/api/actions/resume',{'confirmed':True,'conversation_id':cid}),('/api/actions/transfer-human',{'conversation_id':cid})]:
        assert (await a.post(path, json=payload)).status_code == 409
    assert (await s1.post(f'/api/support/{cid}/reply', json={'message':'late'})).status_code == 409
    assert (await a.post(f'/api/conversations/{cid}/rating', json={'rating':'satisfied'})).status_code == 200
    assert (await a.post(f'/api/conversations/{cid}/rating', json={'rating':'okay'})).status_code == 409
    assert (await a.post(f'/api/conversations/{cid}/rating', json={'rating':'优秀'})).status_code == 422
    assert (await s1.get('/api/support/mine')).json()['items'][0]['rating'] == 'satisfied'

@pytest.mark.asyncio
async def test_persistent_business_mcp_and_ownership(service):
    clients, factory = service
    cid = await new_conv(factory)
    a, s1 = clients['alice'], clients['staff1']
    assert (await a.post('/api/actions/create-refund', json={'conversation_id':cid,'order_id':'bob-1001','reason':'defective_item'})).status_code == 404
    await a.post('/api/actions/transfer-human', json={'conversation_id':cid})
    await s1.post(f'/api/support/{cid}/claim')
    path = f'/api/support/{cid}/orders/alice-1001'
    payload = {'version':1, 'status':'shipped', 'return_code':'AUDITING','status_code':'IN_TRANSIT','city':'上海','description':'上海分拨中心已发出'}
    assert (await s1.patch(path, json=payload)).status_code == 200
    assert (await s1.patch(path, json=payload)).status_code == 409
    assert (await s1.patch(f'/api/support/{cid}/orders/bob-1001', json=payload)).status_code == 404
    assert (await clients['bob'].patch(path, json=payload)).status_code == 403
    from app.tools.builtin.orders import query_order
    from mcp_servers.logistics_server import query_logistics
    from mcp_servers.aftersales_server import query_return_status
    order = await query_order.ainvoke({'user_id':'alice','order_id':'alice-1001'})
    assert order['status'] == 'shipped' and order['version'] == 2
    assert 'error' in await query_order.ainvoke({'user_id':'bob','order_id':'alice-1001'})
    log = await query_logistics(order['tracking_no'])
    assert log['current_city'] == '上海' and log['trace'][-1] == '上海分拨中心已发出'
    assert (await query_return_status('alice-1001'))['return_code'] == 'AUDITING'
    assert (await s1.patch(path, json={'version':2,'status':'awaiting_payment'})).status_code == 409
    assert (await s1.patch(path, json={'version':2,'status_code':'PICKED_UP'})).status_code == 409
    async with factory() as s:
        assert len((await s.scalars(select(BusinessAudit))).all()) == 1
    # New DB connection reads the committed data, rather than any process-local cache.
    engine2 = create_async_engine(str(db.engine.url))
    async with async_sessionmaker(engine2)() as s:
        from app.db.service_models import DemoOrder
        assert (await s.get(DemoOrder, 'alice-1001')).status == 'shipped'
    await engine2.dispose()

@pytest.mark.asyncio
async def test_model_failure_preserves_handoff_option(service, monkeypatch):
    clients, factory = service
    from app.graph import runtime
    async def fail(*args):
        raise ConnectionError('model disconnected')
        yield
    monkeypatch.setattr(runtime, 'stream_turn', fail)
    r = await clients['alice'].post('/api/chat', json={'message':'hello'})
    assert 'transfer_human' in r.text
    assert 'The model is unavailable after retries' in r.text
    cid = (await clients['alice'].get('/api/conversations')).json()['items'][0]['id']
    assert (await clients['alice'].post('/api/actions/transfer-human', json={'conversation_id':cid})).json()['state'] == 'queued'

@pytest.mark.asyncio
async def test_sessions_register_logout_and_csrf(service):
    clients, factory = service
    a=clients['alice']
    assert (await a.post('/api/actions/transfer-human',headers={'Origin':'https://evil.test'},json={'conversation_id':1})).status_code == 403
    anon=clients['anonymous']
    assert (await anon.post('/api/auth/login',json={'username':'alice','password':'incorrect'})).status_code == 401
    r=await anon.post('/api/auth/register',json={'username':'charlie','password':'password123','role':'admin'})
    assert r.status_code == 200 and r.json()['role']=='user'
    assert (await anon.post('/api/auth/register',json={'username':'charlie','password':'password123'})).status_code == 409
    r=await anon.post('/api/auth/login',json={'username':'charlie','password':'password123'})
    assert 'httponly' in r.headers['set-cookie'].lower()
    assert len((await anon.get('/api/orders')).json()['items'])==2
    token=anon.cookies.get('commerce_session')
    await anon.post('/api/auth/logout')
    anon.cookies.set('commerce_session',token)
    assert (await anon.get('/api/auth/me')).status_code == 401

@pytest.mark.asyncio
async def test_agent_can_queue_human_and_graph_stops(service):
    clients,factory=service
    cid=await new_conv(factory)
    from app.tools.builtin.handoff import request_human
    from app.graph.build import _builder
    result=await request_human.ainvoke({'conversation_id':cid,'user_id':'alice','reason':'人工核实'})
    assert result['state']=='queued'
    assert (await clients['staff1'].get('/api/support/queue')).json()['items'][0]['reason']=='人工核实'
    from app.graph import runtime
    with pytest.raises(Exception) as exc:
        await runtime.run_turn('alice','continue',cid)
    assert exc.value.status_code==409

@pytest.mark.asyncio
async def test_agent_handoff_stops_react_graph(service, monkeypatch):
    clients, factory = service
    from app.graph import nodes, runtime
    from app.graph.build import build_graph
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import AIMessage
    from app.tools import registry
    calls = []
    async def resolve(state):
        return {'resolved_query':'请人工处理'}
    async def classify(state):
        return {'intent':'人工', 'route':'business'}
    async def main(state, config=None):
        calls.append('model')
        assert len(calls) == 1, 'No AI turn is allowed after successful human handoff'
        return {'messages':[AIMessage('',tool_calls=[{'name':'request_human','args':{'reason':'需要人工核实'},'id':'handoff'}])], 'steps':1}
    async def specs():
        return registry.builtin_specs()
    async def no_summary(cid):
        pass
    monkeypatch.setattr(nodes, 'resolve_reference', resolve)
    monkeypatch.setattr(nodes, 'classify_intent', classify)
    monkeypatch.setattr(nodes, 'main_agent', main)
    monkeypatch.setattr(registry, 'get_all_specs', specs)
    monkeypatch.setattr(runtime.summarizer, 'maybe_schedule_summary', no_summary)
    monkeypatch.setattr(runtime, '_graph', build_graph(InMemorySaver()))
    out = await runtime.run_turn('alice','请人工处理',None)
    cid = out['conversation_id']
    assert out['state']['human_requested'] is True
    assert calls == ['model']
    state = (await clients['alice'].get(f'/api/conversations/{cid}/service')).json()
    assert state['state'] == 'queued'
    assert 'human-support queue' in (await clients['alice'].get(f'/api/conversations/{cid}/messages')).json()['items'][-1]['content']

@pytest.mark.asyncio
@pytest.mark.integration
async def test_real_mcp_process_reads_committed_updates(service, monkeypatch, tmp_path):
    import os
    import socket
    import subprocess
    import sys
    import json
    from pathlib import Path
    from langchain_mcp_adapters.client import MultiServerMCPClient
    clients, factory = service
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'DATABASE_URL':str(db.engine.url), 'PORT':str(port), 'MOCK_DELAY_SECONDS':'0'}
    root = Path(__file__).resolve().parents[1]
    log = (tmp_path/'mcp.log').open('w')
    proc = subprocess.Popen([sys.executable,'-m','mcp_servers.logistics_server'], cwd=root, env=env,stdout=log,stderr=log)
    try:
        client = MultiServerMCPClient({'logistics':{'transport':'streamable_http','url':f'http://127.0.0.1:{port}/mcp'}}, handle_tool_errors=False)
        tools = None
        for _ in range(60):
            try:
                tools = await client.get_tools()
                break
            except Exception:
                if proc.poll() is not None:
                    pytest.fail((tmp_path/'mcp.log').read_text())
                await asyncio.sleep(.1)
        assert tools, (tmp_path/'mcp.log').read_text()
        tool=next(t for t in tools if t.name=='query_logistics')
        async def query():
            blocks=await tool.ainvoke({'tracking_no':'DEMO-US-alice-1001'})
            return json.loads(next(b['text'] for b in blocks if b.get('type')=='text'))
        assert (await query())['status_code']=='PICKED_UP'
        cid=await new_conv(factory)
        await clients['alice'].post('/api/actions/transfer-human',json={'conversation_id':cid})
        await clients['staff1'].post(f'/api/support/{cid}/claim')
        changed=await clients['staff1'].patch(f'/api/support/{cid}/orders/alice-1001',json={'version':1,'status':'shipped','status_code':'IN_TRANSIT','city':'杭州','description':'杭州已发出'})
        assert changed.status_code==200,changed.text
        result=await query()
        assert result['current_city']=='杭州' and result['status_code']=='IN_TRANSIT'
        assert result['trace'][-1]=='杭州已发出' and result['version']==2
    finally:
        proc.terminate()
        await asyncio.to_thread(proc.wait, timeout=10)
        log.close()

@pytest.mark.asyncio
async def test_sdk_connection_backoff_then_success_and_exhaustion(monkeypatch):
    from app.core.llm import _CumulativeUsageChatOpenAI, get_chat_model
    attempts=[]
    def transport(request):
        attempts.append(request)
        if len(attempts)<3:
            raise httpx.ConnectError('offline', request=request)
        return httpx.Response(200, json={'id':'chatcmpl-test','object':'chat.completion','created':0,'model':'test','choices':[{'index':0,'message':{'role':'assistant','content':'connected'},'finish_reason':'stop'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model=_CumulativeUsageChatOpenAI(model='test',api_key='test',base_url='http://model.test/v1',max_retries=2,http_async_client=client)
        assert (await model.ainvoke('hello')).content=='connected'
        assert len(attempts)==3
    attempts.clear()
    def disconnected(request):
        attempts.append(request)
        raise httpx.ConnectError('offline',request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(disconnected)) as client:
        model=_CumulativeUsageChatOpenAI(model='test',api_key='test',base_url='http://model.test/v1',max_retries=2,http_async_client=client)
        from openai import APIConnectionError
        with pytest.raises(APIConnectionError):
            await model.ainvoke('hello')
        assert len(attempts)==3
    assert get_chat_model().max_retries==2
    assert get_chat_model().request_timeout==20

@pytest.mark.asyncio
async def test_inflight_ai_finishes_before_handoff(service, monkeypatch):
    clients, factory = service
    from app.graph import runtime
    from langchain_core.messages import AIMessage
    cid = await new_conv(factory)
    started, finish = asyncio.Event(), asyncio.Event()
    class FakeGraph:
        async def astream(self, inp, config, stream_mode=None):
            started.set()
            await finish.wait()
            yield ('messages',(AIMessage('交接前的回复'),{'langgraph_node':'main_agent'}))
    async def noop(*args):
        pass
    monkeypatch.setattr(runtime, '_graph', FakeGraph())
    monkeypatch.setattr(runtime, 'settle_layers', noop)
    monkeypatch.setattr(runtime.summarizer, 'maybe_schedule_summary', noop)
    async def generate():
        return [ev async for ev in runtime.stream_turn('alice','hello',cid)]
    generation = asyncio.create_task(generate())
    await asyncio.wait_for(started.wait(),2)
    handoff = asyncio.create_task(clients['alice'].post('/api/actions/transfer-human',json={'conversation_id':cid}))
    try:
        await asyncio.sleep(.05)
        assert not handoff.done(), 'Successful handoff must wait for the in-flight AI turn'
    finally:
        finish.set()
    events = await generation
    assert events[-1]['type']=='done'
    assert (await handoff).json()['state']=='queued'
    assert (await clients['alice'].post('/api/chat',json={'conversation_id':cid,'message':'continue'})).status_code==409

@pytest.mark.asyncio
async def test_mcp_tool_engine_checks_ownership_and_fails_closed(service, monkeypatch):
    clients, factory=service
    from app.tools import engine
    from app.tools.registry import ToolSpec
    cid=await new_conv(factory)
    seen=[]
    class Tool:
        async def ainvoke(self,args):
            seen.append(args)
            return {'tracking_no':args['tracking_no']}
    spec=ToolSpec(name='query_logistics',description='test',json_schema={'type':'object','properties':{'tracking_no':{'type':'string'}},'required':['tracking_no']},tool=Tool(),permission='read',source='mcp')
    call={'name':'query_logistics','id':'test','args':{'tracking_no':'DEMO-US-bob-1001'}}
    for user in ['alice','']:
        out=await engine.execute_tool_call(call,cid,{'query_logistics':spec},user_id=user)
        assert out.status=='permission_denied' and not out.ok
    assert seen==[]
    call['args']['tracking_no']='DEMO-US-alice-1001'
    assert (await engine.execute_tool_call(call,cid,{'query_logistics':spec},user_id='alice')).ok
    async def unavailable(*args):
        raise ConnectionError('database down')
    monkeypatch.setattr(engine,'_mcp_authorized',unavailable)
    result=await engine.execute_tool_call(call,cid,{'query_logistics':spec},user_id='alice')
    assert not result.ok and result.status=='failure'

@pytest.mark.asyncio
async def test_tickets_are_scoped_and_do_not_implicitly_handoff(service):
    clients,factory=service
    cid=await new_conv(factory,'bob')
    r=await clients['bob'].post('/api/actions/create-ticket',json={'conversation_id':cid,'description':'咨询商品','ticket_type':'question'})
    assert r.status_code==200 and r.json()['status']=='pending'
    assert (await clients['bob'].get(f'/api/conversations/{cid}/service')).json()['state']=='ai'
    assert (await clients['alice'].get('/api/tickets')).json()['items']==[]
    ticket=r.json()['ticket_no']
    assert (await clients['staff1'].patch('/api/tickets/'+ticket)).status_code==422
    await clients['bob'].post('/api/actions/transfer-human',json={'conversation_id':cid})
    await clients['staff1'].post(f'/api/support/{cid}/claim')
    assert len((await clients['staff1'].get('/api/tickets?conversation_id='+str(cid))).json()['items'])==1
    assert (await clients['staff1'].post('/api/tickets/'+ticket+'/claim',json={'version':1})).status_code==200
    assert (await clients['staff1'].patch('/api/tickets/'+ticket,json={'version':2,'resolution':'问题已解答'})).status_code==200
    assert (await clients['bob'].get('/api/tickets')).json()['items'][0]['state']=='completed'

@pytest.mark.asyncio
async def test_intent_endpoint_failure_reaches_handoff_fallback(service,monkeypatch):
    """Real graph: a classifier 404 must reach API error handling, not script_reply."""
    clients,factory=service
    from app.graph import nodes,runtime
    from app.core import intent
    from app.graph.build import build_graph
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.runnables import RunnableLambda
    from openai import NotFoundError
    async def resolve(state):return {'resolved_query':'订单什么时候发货？'}
    async def fail(_):
        raise NotFoundError('wrong endpoint',response=httpx.Response(404,request=httpx.Request('POST','https://model.test/api/v1/chat/completions')),body={})
    monkeypatch.setattr(nodes,'resolve_reference',resolve)
    monkeypatch.setattr(intent.llm,'structured',lambda *a,**kw:RunnableLambda(fail))
    monkeypatch.setattr(runtime,'_graph',build_graph(InMemorySaver()))
    r=await clients['alice'].post('/api/chat',json={'message':'订单什么时候发货？'})
    assert r.status_code==200
    assert 'transfer_human' in r.text and 'The model is unavailable after retries' in r.text
    assert '不太确定' not in r.text
    cid=(await clients['alice'].get('/api/conversations')).json()['items'][0]['id']
    assert (await clients['alice'].post('/api/actions/transfer-human',json={'conversation_id':cid})).json()['state']=='queued'

@pytest.mark.asyncio
@pytest.mark.parametrize('component,word',[('embedding','embedding service'),('rerank','reranking service'),('retrieval','search database')])
async def test_rag_failure_reports_correct_dependency_and_handoff(service,monkeypatch,component,word):
    clients,factory=service
    from app.graph import runtime
    from app.core.service_errors import KnowledgeServiceError
    async def fail(*args):
        raise KnowledgeServiceError(component)
        yield
    monkeypatch.setattr(runtime,'stream_turn',fail)
    r=await clients['alice'].post('/api/chat',json={'message':'退货政策'})
    assert word in r.text and 'transfer_human' in r.text
    assert '模型连接重试后仍不可用' not in r.text
    async def fail_sync(*args):raise KnowledgeServiceError(component)
    monkeypatch.setattr(runtime,'run_turn',fail_sync)
    r=await clients['alice'].post('/api/agent',json={'message':'退货政策'})
    assert r.status_code==502 and r.json()['detail']['component']==component


async def test_only_admin_can_start_agent_evaluation(service,monkeypatch):
    clients,_=service
    from app.core import jobs
    started=[]
    async def start(name):started.append(name)
    monkeypatch.setattr(jobs,'start',start)
    for name in ('alice','staff1','anonymous'):
        response=await clients[name].post('/api/jobs/bench-agent')
        assert response.status_code==(401 if name=='anonymous' else 403)
    assert started==[]
    response=await clients['boss'].post('/api/jobs/bench-agent')
    assert response.status_code==200
    assert started==['bench-agent']
