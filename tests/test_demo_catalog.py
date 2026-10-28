"""Demo orders, product tool and RAG use the same documented product identities."""
import pytest
from sqlalchemy import select
from tests.test_service_security import service
from app.demo_catalog import catalog,demo_order_item,find_products
from app.business_store import reconcile_legacy_demo_orders
from app.db.service_models import DemoOrder,BusinessAudit,LogisticsEvent,TicketWorkflow
from app.tools.builtin.orders import query_product


def test_demo_order_models_exist_in_source_document():
    products=catalog()
    assert products and len({p.model for p in products})==len(products)
    assert demo_order_item('1001')=={'product':'Self-Cleaning Litter Box Pro (MH-LP100)','amount':499,'currency':'USD'}
    assert demo_order_item('2002')=={'product':'Everyday Pet Fountain 2L (MH-W20)','amount':39,'currency':'USD'}
    assert all(any(p.order_name==demo_order_item(s)['product'] for p in products) for s in ['1001','2002'])

@pytest.mark.asyncio
async def test_product_lookup_never_invents_unknown_products():
    assert (await query_product.ainvoke({'product_name':'dog food'}))['code']=='product_not_found'
    exact=await query_product.ainvoke({'product_name':'MH-LP100'})
    assert exact['price']==499 and exact['currency']=='USD' and exact['is_demo'] and '2.4 GHz' in exact['spec']
    many=await query_product.ainvoke({'product_name':'Litter Box'})
    assert {p['model'] for p in many['items']}=={'MH-LP50','MH-LP100','MH-LP200'}
    assert (await query_product.ainvoke({'product_name':'MH-LP50'}))['price'] is None

@pytest.mark.asyncio
async def test_new_account_orders_match_catalog_and_query_tool(service):
    c,factory=service
    items=(await c['alice'].get('/api/orders')).json()['items']
    for o in items:
        suffix=o['order_id'].rsplit('-',1)[1]
        assert {k:o[k] for k in ('product','amount','currency')}==demo_order_item(suffix)
        model=next(p.model for p in catalog() if p.order_name==o['product'])
        assert (await query_product.ainvoke({'product_name':model}))['price']==o['amount']
    assert len({o['product'] for o in items})==2

@pytest.mark.asyncio
async def test_legacy_alignment_preserves_lifecycle_links_and_custom_data(service):
    c,factory=service
    ticket=(await c['alice'].post('/api/orders/alice-1001/tickets',json={'description':'请核实订单'})).json()['ticket_no']
    async with factory() as s:
        before_events=len((await s.scalars(select(LogisticsEvent))).all())
        for oid in ['alice-1001','alice-2002']:
            o=await s.get(DemoOrder,oid);o.product='猫粮 5kg';o.amount=199;o.currency='CNY';o.tracking_no='SF-'+oid;o.status='shipped';o.return_code='AUDITING';o.version=3
        o=await s.get(DemoOrder,'bob-1001');o.product='猫粮 5kg';o.amount=88
        o=await s.get(DemoOrder,'bob-2002');o.product='自定义商品';o.amount=199
        await s.commit()
    async with factory() as s:
        assert await reconcile_legacy_demo_orders(s)==2
        await s.commit()
    async with factory() as s:
        assert await reconcile_legacy_demo_orders(s)==0
        await s.commit()
        for suffix in ['1001','2002']:
            o=await s.get(DemoOrder,'alice-'+suffix)
            assert o.product==demo_order_item(suffix)['product'] and o.amount==demo_order_item(suffix)['amount']
            assert o.status=='shipped' and o.return_code=='AUDITING' and o.version==4
            assert o.tracking_no=='DEMO-US-alice-'+suffix
            assert o.currency=='USD'
        assert (await s.get(DemoOrder,'bob-1001')).amount==88
        assert (await s.get(DemoOrder,'bob-2002')).product=='自定义商品'
        assert (await s.get(TicketWorkflow,ticket)).order_id=='alice-1001'
        assert len((await s.scalars(select(LogisticsEvent))).all())==before_events
        audit=(await s.scalars(select(BusinessAudit))).all()
        assert len(audit)==2 and all(a.actor_id=='system:demo_catalog' for a in audit)


@pytest.mark.asyncio
async def test_english_and_chinese_legacy_offers_migrate_without_touching_custom_events(service):
    c, factory = service
    async with factory() as s:
        for oid, product, amount in [('alice-1001', '智能猫砂盆 Pro（MH-LP100）', 1999),
                                     ('alice-2002', 'Everyday Pet Fountain 2L (MH-W20)', 299)]:
            order = await s.get(DemoOrder, oid)
            order.product, order.amount, order.currency = product, amount, 'CNY'
            order.tracking_no = 'SF-' + oid
            events = (await s.scalars(select(LogisticsEvent).where(LogisticsEvent.order_id == oid))).all()
            events[0].city, events[0].description = '深圳', '深圳仓库已揽件'
        s.add(LogisticsEvent(order_id='alice-1001', status_code='IN_TRANSIT', city='Phoenix, AZ', description='Custom carrier update'))
        await s.commit()
    async with factory() as s:
        assert await reconcile_legacy_demo_orders(s) == 2
        await s.commit()
    orders = (await c['alice'].get('/api/orders')).json()['items']
    assert {(o['amount'], o['currency']) for o in orders} == {(499, 'USD'), (39, 'USD')}
    detail = (await c['alice'].get('/api/orders/alice-1001')).json()
    assert any(e['city'] == 'Los Angeles, CA' for e in detail['events'])
    assert any(e['description'] == 'Custom carrier update' for e in detail['events'])
    from app.tools.builtin.orders import query_order
    result = await query_order.ainvoke({'order_id':'alice-1001','user_id':'alice'})
    assert result['currency'] == 'USD' and result['amount'] == 499

@pytest.mark.asyncio
async def test_legacy_currency_column_preserves_unrecognized_amounts(monkeypatch, tmp_path):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    import app.db.base as db
    from app.bootstrap import ensure_order_currency
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/legacy.sqlite')
    monkeypatch.setattr(db, 'engine', engine)
    async with engine.begin() as conn:
        await conn.execute(text('CREATE TABLE demo_orders (order_id VARCHAR(96), amount INTEGER)'))
        await conn.execute(text("INSERT INTO demo_orders VALUES ('custom', 888)"))
    await ensure_order_currency()
    await ensure_order_currency()
    async with engine.connect() as conn:
        row = (await conn.execute(text('SELECT amount,currency FROM demo_orders'))).one()
        assert row.amount == 888 and row.currency == 'CNY'
    await engine.dispose()
