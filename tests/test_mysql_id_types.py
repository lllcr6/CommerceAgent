"""Guard the MySQL signedness contract even when most integration tests use SQLite."""
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateTable
from app.db.models import Conversation, Message, Ticket
from app.db.service_models import HumanSession


def test_conversation_foreign_keys_match_unsigned_migration_ids():
    dialect = mysql.dialect()
    assert Conversation.__table__.c.id.type.compile(dialect) == "BIGINT UNSIGNED"
    for table in [Message.__table__, Ticket.__table__, HumanSession.__table__]:
        assert table.c.conversation_id.type.compile(dialect) == "BIGINT UNSIGNED"
    ddl = str(CreateTable(HumanSession.__table__).compile(dialect=dialect))
    assert "conversation_id BIGINT UNSIGNED" in ddl
    assert "FOREIGN KEY(conversation_id) REFERENCES conversations (id)" in ddl


def test_sqlite_ids_still_support_integer_primary_keys():
    dialect = sqlite.dialect()
    for table in [Conversation.__table__, Message.__table__, HumanSession.__table__]:
        column = table.c.conversation_id if table is HumanSession.__table__ else table.c.id
        assert column.type.compile(dialect) == "INTEGER"


def test_bootstrap_registers_existing_tables_in_fresh_process():
    import subprocess
    import sys
    subprocess.run([sys.executable, "-c", "from app.bootstrap import SERVICE_TABLES; from sqlalchemy.schema import sort_tables; assert 'conversations' in SERVICE_TABLES[0].metadata.tables; sort_tables(SERVICE_TABLES)"], check=True, capture_output=True)
