import pathlib

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings


def pytest_addoption(parser):
    parser.addoption(
        "--offline", action="store_true", default=False,
        help="Skip tests that require MySQL, Milvus, or live MCP processes.",
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        # Fixture closure includes indirect database dependencies as well.
        if "_test_engine" in item.fixturenames:
            item.add_marker(pytest.mark.integration)
        if config.getoption("--offline") and item.get_closest_marker("integration"):
            item.add_marker(pytest.mark.skip(reason="External service integration is disabled by --offline"))


_DDL_FILES = [
    pathlib.Path(__file__).resolve().parent.parent / "sql" / "001_core_tables.sql",
    pathlib.Path(__file__).resolve().parent.parent / "sql" / "003_knowledge_tables.sql",

    pathlib.Path(__file__).resolve().parent.parent / "sql" / "005_knowledge_review.sql",
    pathlib.Path(__file__).resolve().parent.parent / "sql" / "006_rag_quality_tables.sql",
    pathlib.Path(__file__).resolve().parent.parent / "sql" / "008_conversation_summary.sql",

    pathlib.Path(__file__).resolve().parent.parent / "sql" / "009_conversation_memory_layers.sql",
    pathlib.Path(__file__).resolve().parent.parent / "sql" / "010_tool_audit_tables.sql",
    pathlib.Path(__file__).resolve().parent.parent / "sql" / "011_flywheel_tables.sql",
    pathlib.Path(__file__).resolve().parent.parent / "sql" / "012_topic_classification_tables.sql",
]


_TABLES = ["chat_generations", "ticket_events", "ticket_workflows", "human_sessions", "logistics_events", "demo_orders", "login_sessions", "business_audit", "accounts",
           "faith_cases", "topic_classifications", "low_confidence_questions", "review_queue", "eval_runs",
           "conversation_summaries",
           "messages", "tickets", "tool_audit_logs", "conversations", "faq",
           "qa_extraction_staging", "knowledge_chunks"]

_TEST_URL = settings.test_database_url
_DB_NAME = _TEST_URL.rsplit("/", 1)[1]
_SERVER_URL = _TEST_URL.rsplit("/", 1)[0]


def _split_sql(sql: str) -> list[str]:

    stmts, buf, in_str = [], [], False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
        if ch == ";" and not in_str:
            stmts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    stmts.append("".join(buf))
    return stmts


def _create_table_stmts() -> list[str]:

    stmts: list[str] = []
    for ddl in _DDL_FILES:
        raw = ddl.read_text(encoding="utf-8")
        sql = "\n".join(ln for ln in raw.splitlines() if not ln.lstrip().startswith("--"))

        for s in _split_sql(sql):
            s = s.strip()
            if not s:
                continue
            if s.upper().startswith(("CREATE TABLE", "ALTER TABLE")):
                stmts.append(s)
            elif "CREATE TABLE" in s.upper() or "ALTER TABLE" in s.upper():

                raise ValueError(f"DDL statement splitting failed({ddl.name}): {s[:80]!r}")
    return stmts


@pytest.fixture(autouse=True)
def _no_langfuse(monkeypatch):

    monkeypatch.setattr("app.config.settings.langfuse_public_key", "")


@pytest_asyncio.fixture()
async def _test_engine():

    admin = create_async_engine(_SERVER_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(
            text(f"CREATE DATABASE IF NOT EXISTS {_DB_NAME} CHARACTER SET utf8mb4")
        )
    await admin.dispose()

    engine = create_async_engine(_TEST_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for t in _TABLES:
            await conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        for stmt in _create_table_stmts():


            await conn.exec_driver_sql(stmt)
        from app.db.service_models import SERVICE_TABLES
        await conn.run_sync(lambda c: SERVICE_TABLES[0].metadata.create_all(c, tables=SERVICE_TABLES))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session_factory(_test_engine, monkeypatch):

    factory = async_sessionmaker(_test_engine, expire_on_commit=False)
    monkeypatch.setattr("app.db.base.async_session", factory)
    return factory


@pytest_asyncio.fixture()
async def db_clean():

    yield


@pytest.fixture()
def client(api_unit_session):

    from app.api.actions import router as actions_router
    test_app = FastAPI()
    test_app.include_router(actions_router)
    api_unit_session(test_app)
    return TestClient(test_app)


@pytest_asyncio.fixture
async def business_db(monkeypatch, tmp_path):
    """Persisted demo orders for tool/node unit tests; independent of MySQL infrastructure."""
    import app.db.base as db
    from app.db.service_models import Account, DemoOrder, LogisticsEvent
    from app.business_store import seed_orders
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/business.sqlite")
    async with engine.begin() as c:
        await c.run_sync(lambda conn: db.Base.metadata.create_all(conn, tables=[Account.__table__, DemoOrder.__table__, LogisticsEvent.__table__]))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "async_session", factory)
    monkeypatch.setattr(db, "engine", engine)
    async with factory() as s:
        for uid in ["u1", "u-42", "u-agent", "u-someone-else", "u-alice", "u-bob", "u-mock"]:
            s.add(Account(id=uid, password_hash="unused", role="user"))
            await s.flush()
            await seed_orders(s, uid)
        await s.commit()
    yield factory
    await engine.dispose()


@pytest.fixture
def api_unit_session(monkeypatch):
    """Route serialization tests use explicit auth/access stubs.

    Real session and authorization integration tests live in test_service_security.py
    and deliberately do not use this fixture.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.auth import current_user
    from app.main import app
    from app.api import actions, agent, chat, conversations, feedback
    from app.db import repository
    # These are wire-format unit tests. The durable supervisor is exercised with
    # real sessions/database in test_generation_lifecycle.py.
    from app.core import generations
    import uuid
    sources = {}
    async def start_inline(cid, uid, source, **kwargs):
        run_id = uuid.uuid4().hex
        sources[run_id] = source
        return run_id
    async def stream_inline(cid, run_id):
        async for frame in sources[run_id]():
            yield frame
    monkeypatch.setattr(generations, "start", start_inline)
    monkeypatch.setattr(generations, "stream", stream_inline)
    user = SimpleNamespace(id="u1", role="user")
    async def identity():
        return user
    async def accessible(cid, principal, **kw):
        return SimpleNamespace(id=cid, user_id=principal.id, status="active")
    monkeypatch.setitem(app.dependency_overrides, current_user, identity)
    for module in [actions, agent, chat, conversations, feedback]:
        monkeypatch.setattr(module, "conversation_access", accessible)
    monkeypatch.setattr(repository, "create_conversation", AsyncMock(return_value=1))
    monkeypatch.setattr("app.business_store.owns_order", AsyncMock(return_value=True))
    def configure(test_app):
        test_app.dependency_overrides[current_user] = identity
    return configure


@pytest.fixture(autouse=True)
def isolate_local_usage_records(tmp_path, monkeypatch):
    from app import usage_store
    monkeypatch.setattr(usage_store, 'PATH', tmp_path / 'model_usage.sqlite')
