"""Browser disconnect cancels an observer, not the model or MySQL work."""
import asyncio
import json
import httpx
import pytest
from langchain_core.messages import AIMessageChunk
from sqlalchemy import select,func
from tests.test_service_security import service,new_conv
from app.core import generations
from app.graph import runtime
from app.db.models import Message
from app.db.service_models import ChatGeneration,Account
import app.db.base as db

pytestmark=pytest.mark.asyncio

async def exercise_disconnect(client,factory,monkeypatch,owner):
    from app.main import app
    from app.db import repository
    cid=await new_conv(factory,owner)
    release=asyncio.Event();disconnected=asyncio.Event();began=asyncio.Event()
    cancelled=[]
    class Graph:
        async def astream(self,*args,**kwargs):
            try:
                yield ('messages',(AIMessageChunk('前半段'),{'langgraph_node':'main_agent'}))
                began.set()
                await release.wait()
                yield ('messages',(AIMessageChunk('后半段'),{'langgraph_node':'main_agent'}))
                await repository.append_message(cid,'assistant',content='前半段后半段')
            except asyncio.CancelledError:
                cancelled.append(True);raise
    async def noop(*args):pass
    monkeypatch.setattr(runtime,'_graph',Graph())
    monkeypatch.setattr(runtime,'settle_layers',noop)
    monkeypatch.setattr(runtime.summarizer,'maybe_schedule_summary',noop)
    body=json.dumps({'conversation_id':cid,'message':'请慢慢生成'}).encode()
    request=client.build_request('POST','/api/chat',content=body,headers={'Content-Type':'application/json'})
    first=True;sent=[]
    async def receive():
        nonlocal first
        if first:
            first=False;return {'type':'http.request','body':body,'more_body':False}
        await disconnected.wait();return {'type':'http.disconnect'}
    async def send(message):
        sent.append(message)
        if message['type']=='http.response.body' and '前半段'.encode() in message.get('body',b''):
            disconnected.set()
    scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.0'},'http_version':'1.1',
           'method':'POST','scheme':'http','path':'/api/chat','raw_path':b'/api/chat',
           'query_string':b'','root_path':'','headers':[(key.lower(),value) for key,value in request.headers.raw],'server':('test',80),'client':('test',123)}
    producer=None
    try:
        await asyncio.wait_for(app(scope,receive,send),5)
        assert disconnected.is_set() and began.is_set() and not cancelled
        snapshot=(await client.get(f'/api/conversations/{cid}/generation')).json()
        assert snapshot['state']=='running'
        run_id=snapshot['run_id'];producer=generations._tasks[run_id]
        assert not producer.done()
        assert (await client.post('/api/chat',json={'conversation_id':cid,'message':'重复请求'})).status_code==409
        release.set();await asyncio.wait_for(asyncio.shield(producer),5)
        assert not cancelled
        snapshot=(await client.get(f'/api/conversations/{cid}/generation')).json()
        assert snapshot['state']=='completed'
        for _ in range(2):
            replay=await client.get(f'/api/conversations/{cid}/generation/events',params={'run_id':run_id})
            assert replay.status_code==200 and '前半段' in replay.text and '后半段' in replay.text
        async with factory() as s:
            messages=(await s.scalars(select(Message).where(Message.conversation_id==cid).order_by(Message.id))).all()
            assert [(m.role,m.content) for m in messages]==[('user','请慢慢生成'),('assistant','前半段后半段')]
            assert (await s.get(ChatGeneration,cid)).state=='completed'
        return cid,run_id
    finally:
        release.set()
        if producer:await asyncio.wait_for(asyncio.shield(producer),5)

async def test_disconnect_and_reconnect_keep_generation_running(service,monkeypatch):
    c,factory=service
    cid,run_id=await exercise_disconnect(c['alice'],factory,monkeypatch,'alice')
    for name in ['bob','staff1']:
        assert (await c[name].get(f'/api/conversations/{cid}/generation')).status_code==(404 if name=='bob' else 403)
        assert (await c[name].get(f'/api/conversations/{cid}/generation/events',params={'run_id':run_id})).status_code==(404 if name=='bob' else 403)
    assert (await c['anonymous'].get(f'/api/conversations/{cid}/generation')).status_code==401

async def test_waiting_confirmation_survives_navigation_and_resume(service,monkeypatch):
    c,factory=service;cid=await new_conv(factory)
    async def pause(*args):
        yield {'type':'interrupt','kind':'confirm_ticket','conversation_id':cid,'preview':{'description':'请确认'}}
    async def resume(*args):
        yield {'type':'delta','text':'确认后的结果'}
        yield {'type':'done','conversation_id':cid}
    monkeypatch.setattr(runtime,'stream_turn',pause)
    monkeypatch.setattr(runtime,'stream_resume',resume)
    response=await c['alice'].post('/api/chat',json={'conversation_id':cid,'message':'创建工单'})
    assert 'confirm_ticket' in response.text
    snap=(await c['alice'].get(f'/api/conversations/{cid}/generation')).json()
    assert snap['state']=='waiting'
    assert '请确认' in (await c['alice'].get(f'/api/conversations/{cid}/generation/events',params={'run_id':snap['run_id']})).text
    assert (await c['alice'].post('/api/chat',json={'conversation_id':cid,'message':'跳过确认'})).status_code==409
    result=await c['alice'].post('/api/actions/resume',json={'conversation_id':cid,'confirmed':True})
    assert '确认后的结果' in result.text
    assert (await c['alice'].get(f'/api/conversations/{cid}/generation')).json()['state']=='completed'
    assert (await c['alice'].post('/api/actions/resume',json={'conversation_id':cid,'confirmed':True})).status_code==409

async def test_restart_marks_running_failed_without_reexecuting_tools(service):
    c,factory=service;cid=await new_conv(factory)
    async with factory() as s:
        s.add(ChatGeneration(conversation_id=cid,run_id='stale-run',state='running',frames=['data: {"delta":"已有内容"}\n\n']))
        await s.commit()
    await generations.recover_interrupted()
    snap=await generations.snapshot(cid)
    assert snap['state']=='failed' and '已有内容' in ''.join(snap['frames'])
    assert 'The service restarted' in ''.join(snap['frames'])
    await generations.recover_interrupted()
    assert (await generations.snapshot(cid))==snap

async def test_real_mysql_disconnect_does_not_cancel_db_cleanup(db_session_factory,monkeypatch):
    from app.auth import password_hash
    from app.main import app
    engine=db_session_factory.kw['bind'];monkeypatch.setattr(db,'engine',engine)
    async with db_session_factory() as s:
        s.add(Account(id='background-mysql-user',role='user',password_hash=password_hash('password123')))
        await s.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.post('/api/auth/login',json={'username':'background-mysql-user','password':'password123'})).status_code==200
        await exercise_disconnect(client,db_session_factory,monkeypatch,'background-mysql-user')
        # Reuse the MySQL pool after the cancelled HTTP observer and final commit.
        assert (await client.get('/api/conversations')).status_code==200

async def test_simultaneous_start_only_launches_one_producer(service):
    c,factory=service;cid=await new_conv(factory);release=asyncio.Event();count=[]
    async def source():
        count.append(1);await release.wait();yield 'data: [DONE]\n\n'
    results=await asyncio.gather(generations.start(cid,'alice',source),generations.start(cid,'alice',source),return_exceptions=True)
    ids=[r for r in results if isinstance(r,str)]
    try:
        assert len(ids)==1 and len([r for r in results if getattr(r,'status_code',None)==409])==1
    finally:
        release.set()
        for run_id in ids:
            task=generations._tasks.get(run_id)
            if task:await asyncio.wait_for(asyncio.shield(task),5)
    assert count==[1]

async def test_server_cancel_marks_partial_run_failed(service):
    c,factory=service;cid=await new_conv(factory);began=asyncio.Event()
    async def source():
        yield 'data: {"delta":"已生成部分"}\n\n'
        began.set();await asyncio.Event().wait()
    run_id=await generations.start(cid,'alice',source)
    await asyncio.wait_for(began.wait(),2)
    task=generations._tasks[run_id];task.cancel();await task
    result=await generations.snapshot(cid)
    assert result['state']=='failed'
    assert '已生成部分' in ''.join(result['frames']) and 'interrupted this reply' in ''.join(result['frames'])


async def test_stopping_benchmark_cancels_only_that_accounts_background_generations(service):
    _,factory=service
    async with factory() as session:
        session.add(Account(id='bench_stop_test',role='user',password_hash='unused-test-hash'))
        await session.commit()
    bench=await new_conv(factory,'bench_stop_test');ordinary=await new_conv(factory,'alice')
    began=[asyncio.Event(),asyncio.Event()]
    def source(index):
        async def stream():
            yield 'data: {"delta":"partial"}\n\n'
            began[index].set();await asyncio.Event().wait()
        return stream
    bid=await generations.start(bench,'bench_stop_test',source(0))
    oid=await generations.start(ordinary,'alice',source(1))
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in began)),2)
        assert await generations.stop_benchmark_account('bench_stop_test')==1
        assert (await generations.snapshot(bench))['state']=='failed'
        assert 'Evaluation stopped by the administrator.' in ''.join((await generations.snapshot(bench))['frames'])
        assert not generations._tasks[oid].done()
        assert (await generations.snapshot(ordinary))['state']=='running'
        with pytest.raises(ValueError):await generations.stop_benchmark_account('alice')
    finally:
        for rid in (bid,oid):
            task=generations._tasks.get(rid)
            if task and not task.done():task.cancel();await task

async def test_benchmark_request_id_replays_existing_generation(service,monkeypatch):
    clients,factory=service
    await clients['alice'].post('/api/auth/register',json={'username':'bench_replay','password':'testing-pass-123'})
    await clients['alice'].post('/api/auth/login',json={'username':'bench_replay','password':'testing-pass-123'})
    response=await clients['alice'].post('/api/benchmark/conversations')
    assert response.status_code==200
    cid=response.json()['conversation_id'];calls=[]
    async def source(*args):
        calls.append(True)
        yield {'type':'session','conversation_id':cid}
        yield {'type':'delta','text':'Saved answer'}
        yield {'type':'done','conversation_id':cid}
    monkeypatch.setattr(runtime,'stream_turn',source)
    body={'conversation_id':cid,'message':'Shipping?'};headers={'X-Benchmark-Request':'a'*32}
    first=await clients['alice'].post('/api/chat',json=body,headers=headers)
    second=await clients['alice'].post('/api/chat',json=body,headers=headers)
    assert first.status_code==second.status_code==200
    assert 'Saved answer' in second.text
    assert len(calls)==1
    assert (await clients['bob'].post('/api/benchmark/conversations')).status_code==403
