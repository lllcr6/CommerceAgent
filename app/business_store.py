from sqlalchemy import select
from fastapi import HTTPException
import app.db.base as db
from app.db.service_models import DemoOrder, LogisticsEvent, BusinessAudit
from app.demo_catalog import demo_order_item, LEGACY_PRODUCT

async def seed_orders(s, uid):
    # Globally unique IDs, never share demo order numbers between owners.
    for suffix in ("1001", "2002"):
        oid = f"{uid}-{suffix}"
        s.add(DemoOrder(order_id=oid, user_id=uid, tracking_no=f"DEMO-US-{oid}", **demo_order_item(suffix)))
        await s.flush()
        s.add(LogisticsEvent(order_id=oid, status_code="PICKED_UP", city="Los Angeles, CA", description="Carrier picked up the package in Los Angeles, CA."))

def order_dict(o):
    return {k: getattr(o, k) for k in ("order_id", "user_id", "status", "amount", "currency", "product", "tracking_no", "return_code", "warranty_code", "warranty_until", "version")} | {"created_at": o.created_at.isoformat()}

async def order_snapshot(order_id):
    async with db.async_session() as s:
        o = await s.get(DemoOrder, order_id)
        return order_dict(o) if o else {}

async def list_user_orders(uid):
    async with db.async_session() as s:
        return [order_dict(o) for o in (await s.scalars(select(DemoOrder).where(DemoOrder.user_id == uid))).all()]

async def owns_order(uid, oid):
    async with db.async_session() as s:
        o = await s.get(DemoOrder, oid)
        return bool(uid and o and o.user_id == uid)

async def logistics(tracking_no):
    async with db.async_session() as s:
        o = await s.scalar(select(DemoOrder).where(DemoOrder.tracking_no == tracking_no))
        if not o:
            return {"error": "Tracking information not found."}
        events = (await s.scalars(select(LogisticsEvent).where(LogisticsEvent.order_id == o.order_id).order_by(LogisticsEvent.id))).all()
        last = events[-1] if events else None
        return {"tracking_no": tracking_no, "status_code": last.status_code if last else "PICKED_UP",
                "current_city": last.city if last else "", "trace": [e.description for e in events], "version": o.version}


# Exact former seed identities and prices; do not rewrite custom orders.
LEGACY_OFFERS = {
    '1001': {(LEGACY_PRODUCT, 199), ('智能猫砂盆 Pro（MH-LP100）', 1999),
             ('智能猫砂盆 Pro (MH-LP100)', 1999), ('Self-Cleaning Litter Box Pro (MH-LP100)', 1999)},
    '2002': {(LEGACY_PRODUCT, 199), ('自动饮水机（MH-W20）', 299),
             ('自动饮水机 (MH-W20)', 299), ('Everyday Pet Fountain 2L (MH-W20)', 299)},
}


async def reconcile_legacy_demo_orders(s):
    """Migrate exact legacy demo defaults to explicit USD offers, with an audit trail.

    Preserve owners, order IDs, lifecycle and ticket links. Custom prices/products
    and manually entered tracking events are not converted or relabeled.
    """
    rows = (await s.scalars(select(DemoOrder).with_for_update())).all()
    changed = 0
    for order in rows:
        suffix = next((v for v in ORDER_SUFFIXES if order.order_id == f'{order.user_id}-{v}'), None)
        if not suffix or order.tracking_no != f'SF-{order.order_id}':
            continue
        if (order.product, order.amount) not in LEGACY_OFFERS[suffix] or order.currency != 'CNY':
            continue
        item = demo_order_item(suffix)
        before = {k: getattr(order, k) for k in ('product', 'amount', 'currency', 'tracking_no')}
        order.product = item['product']
        order.amount = item['amount']
        order.currency = item['currency']
        order.tracking_no = f'DEMO-US-{order.order_id}'
        order.version += 1
        events = (await s.scalars(select(LogisticsEvent).where(LogisticsEvent.order_id == order.order_id))).all()
        event_changes = []
        for event in events:
            if event.city == '深圳' and event.description == '深圳仓库已揽件':
                event_changes.append({'id': event.id, 'before': {'city': event.city, 'description': event.description}})
                event.city = 'Los Angeles, CA'
                event.description = 'Carrier picked up the package in Los Angeles, CA.'
        after = {k: getattr(order, k) for k in before}
        s.add(BusinessAudit(actor_id='system:demo_catalog', order_id=order.order_id,
                            changes={'operation': 'us_demo_catalog_migration', 'before': before, 'after': after,
                                     'logistics_updated': event_changes, 'pricing_basis': 'New fictional USD demo offers; not a currency conversion'}))
        changed += 1
    return changed


ORDER_SUFFIXES = ('1001', '2002')
