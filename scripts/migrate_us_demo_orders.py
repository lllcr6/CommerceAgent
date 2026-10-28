"""Migrate exact legacy demo orders to fictional USD offers. Default: read-only plan.

--apply writes a local recovery snapshot, adds an explicit currency field if
needed, and updates known legacy seed records with an audit trail. Custom order
values are preserved. No currency conversion or external service calls occur.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from sqlalchemy import text
from app.db.base import engine, async_session
from app.bootstrap import ensure_order_currency
from app.business_store import LEGACY_OFFERS, reconcile_legacy_demo_orders
from app.demo_catalog import demo_order_item


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    async with engine.connect() as conn:
        orders = [dict(row) for row in (await conn.execute(text('SELECT * FROM demo_orders'))).mappings()]
        events = [dict(row) for row in (await conn.execute(text('SELECT * FROM logistics_events'))).mappings()]
    matches = []
    for row in orders:
        suffix = next((v for v in LEGACY_OFFERS if row['order_id'] == f"{row['user_id']}-{v}"), None)
        if suffix and row['tracking_no'] == f"SF-{row['order_id']}" and row.get('currency', 'CNY') == 'CNY' and (row['product'], row['amount']) in LEGACY_OFFERS[suffix]:
            matches.append(row['order_id'])
    print(f'Known legacy demo orders to update: {len(matches)}. Other order values are preserved.')
    print('New fictional offers:', {suffix: demo_order_item(suffix) for suffix in LEGACY_OFFERS})
    if not args.apply:
        print('Read-only plan. Pass --apply to back up and migrate.')
        return
    backup = Path('data/runtime/order-backups') / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps({'orders': orders, 'logistics_events': events}, default=str, ensure_ascii=False), encoding='utf-8')
    backup.chmod(0o600)
    await ensure_order_currency()
    async with async_session() as session:
        changed = await reconcile_legacy_demo_orders(session)
        await session.commit()
    print(f'Migrated {changed} demo orders. Recovery snapshot: {backup}')


if __name__ == '__main__':
    async def run():
        try:
            await main()
        finally:
            await engine.dispose()
    asyncio.run(run())
