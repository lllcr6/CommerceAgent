"""Real MySQL regression: original SQL schema + additive service ORM tables.

Uses the dedicated TEST_DATABASE_URL rebuilt by the existing test fixture.
"""
import httpx
from sqlalchemy import inspect
import app.db.base as db
from app.auth import password_hash
from app.bootstrap import initialize_service_tables
from app.db.models import Conversation
from app.db.service_models import Account, SERVICE_TABLES


async def test_mysql_bootstrap_and_human_lifecycle(db_session_factory, monkeypatch):
    engine = db_session_factory.kw['bind']
    monkeypatch.setattr(db, 'engine', engine)
    # conversations was created from the original SQL, not ORM-generated DDL.
    await initialize_service_tables()
    await initialize_service_tables()
    async with engine.connect() as conn:
        def structure(c):
            inspector = inspect(c)
            columns = {col['name']: col for col in inspector.get_columns('human_sessions')}
            assert columns['conversation_id']['type'].unsigned is True
            assert inspector.get_foreign_keys('human_sessions')
            assert all(inspector.has_table(t.name) for t in SERVICE_TABLES)
        await conn.run_sync(structure)
    async with db_session_factory() as s:
        s.add_all([Account(id='mysql-user', role='user', password_hash=password_hash('password123')),
                   Account(id='mysql-support', role='support', password_hash=password_hash('password123'))])
        conv = Conversation(user_id='mysql-user')
        s.add(conv)
        await s.commit()
        cid = conv.id
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as user, httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as staff:
        for client, name in [(user,'mysql-user'),(staff,'mysql-support')]:
            r = await client.post('/api/auth/login',json={'username':name,'password':'password123'})
            assert r.status_code == 200, r.text
        r = await user.post('/api/actions/transfer-human',json={'conversation_id':cid})
        assert r.status_code == 200 and r.json()['state']=='queued', r.text
        assert (await staff.post(f'/api/support/{cid}/claim')).status_code == 200
        assert (await staff.post(f'/api/support/{cid}/reply',json={'message':'人工回复 MySQL 验收'})).status_code == 200
        assert (await user.get(f'/api/conversations/{cid}/messages')).json()['items'][0]['content']=='人工回复 MySQL 验收'
        assert (await staff.post(f'/api/support/{cid}/close')).status_code == 200
        assert (await user.post(f'/api/conversations/{cid}/rating',json={'rating':'satisfied'})).status_code == 200
        assert (await user.post('/api/chat',json={'conversation_id':cid,'message':'继续'})).status_code == 409


async def test_mysql_independent_ticket_flow_and_backfill(db_session_factory, monkeypatch):
    from app.db.models import Ticket
    from app.db.service_models import TicketWorkflow, TicketEvent
    from sqlalchemy import select
    engine = db_session_factory.kw['bind']
    monkeypatch.setattr(db, 'engine', engine)
    async with db_session_factory() as s:
        s.add_all([Account(id='ticket-user',role='user',password_hash=password_hash('password123')),
                   Account(id='ticket-staff',role='support',password_hash=password_hash('password123'))])
        conv=Conversation(user_id='ticket-user')
        s.add(conv)
        await s.flush()
        cid=conv.id
        s.add(Ticket(ticket_no='legacy-mysql-ticket',conversation_id=cid,description='旧工单',ticket_type='question',status='pending'))
        await s.commit()
    await initialize_service_tables()
    await initialize_service_tables()
    async with db_session_factory() as s:
        assert (await s.get(TicketWorkflow,'legacy-mysql-ticket')).state=='pending'
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as user, httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as staff:
        for client,name in [(user,'ticket-user'),(staff,'ticket-staff')]:
            assert (await client.post('/api/auth/login',json={'username':name,'password':'password123'})).status_code==200
        created=await user.post('/api/actions/create-ticket',json={'conversation_id':cid,'description':'仅工单售后','ticket_type':'after_sales'})
        assert created.status_code==200,created.text
        path='/api/tickets/'+created.json()['ticket_no']
        assert len((await staff.get('/api/tickets?scope=pending')).json()['items'])==2
        assert (await staff.post(path+'/claim',json={'version':1})).status_code==200
        assert (await staff.post(path+'/records',json={'version':2,'content':'仅内部可见'})).status_code==200
        assert '仅内部可见' not in str((await user.get(path)).json())
        assert (await staff.post(path+'/complete',json={'version':3,'resolution':'处理完毕'})).status_code==200
        assert (await user.get(path)).json()['resolution']=='处理完毕'
        assert (await user.get(f'/api/conversations/{cid}/service')).json()['state']=='ai'
    await initialize_service_tables()
    async with db_session_factory() as s:
        assert (await s.get(TicketWorkflow,created.json()['ticket_no'])).state=='completed'
        assert len((await s.scalars(select(TicketEvent))).all())==4
