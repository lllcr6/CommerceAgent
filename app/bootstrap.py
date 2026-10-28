"""Additive schema installation. Account creation is an explicit CLI action."""
from sqlalchemy import inspect, text
import app.db.base as db
from app.db import models  # Register existing FK targets, including conversations, for CLI use.
from app.db.service_models import SERVICE_TABLES

async def ensure_order_currency():
    """Existing amounts remain CNY until an exact known demo seed is migrated."""
    async with db.engine.begin() as conn:
        columns = await conn.run_sync(lambda c: {col['name'] for col in inspect(c).get_columns('demo_orders')})
        if 'currency' not in columns:
            await conn.execute(text("ALTER TABLE demo_orders ADD COLUMN currency VARCHAR(3) NOT NULL DEFAULT 'CNY'"))

async def initialize_service_tables():
    async with db.engine.begin() as conn:
        await conn.run_sync(lambda c: SERVICE_TABLES[0].metadata.create_all(c, tables=SERVICE_TABLES))
    await ensure_order_currency()
    from app.db.ticket_workflow import backfill_workflows
    async with db.async_session() as session:
        await backfill_workflows(session)
        from app.business_store import reconcile_legacy_demo_orders
        await reconcile_legacy_demo_orders(session)
        await session.commit()
