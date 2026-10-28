"""Remove identified obsolete knowledge records while preserving the active corpus.

Default: read-only plan. --apply backs up SQL rows and legacy vectors locally,
then removes the verified legacy rows and the inactive `knowledge` collection.
No embeddings or chat-provider requests are made. English chunk IDs are preserved.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from sqlalchemy import delete, select

from app.db.base import async_session, engine
from app.db.models import KnowledgeChunk
from app.kb import milvus_client as m
from scripts.prepare_english_rag import identity, source_chunks


def split_corpus(rows: list[dict], authored: list[dict]) -> tuple[list[dict], list[dict]]:
    expected = {identity(c) for c in authored}
    english = [r for r in rows if identity(r) in expected]
    legacy = [r for r in rows if identity(r) not in expected]
    if len(english) != len(expected) or {identity(r) for r in english} != expected:
        raise ValueError('English source content is missing or duplicated; cleanup aborted')
    if any(not re.search(r'[\u3400-\u9fff]', r['question'] + r['answer']) for r in legacy):
        raise ValueError('Unrecognized non-Chinese knowledge found; cleanup aborted')
    return english, legacy


def sql_dict(row) -> dict:
    return {col.name: getattr(row, col.name) for col in KnowledgeChunk.__table__.columns}


async def run(apply: bool) -> None:
    if m.COLLECTION != 'knowledge_en_v1':
        raise ValueError('Cleanup requires the active English collection knowledge_en_v1')
    async with async_session() as session:
        query = select(KnowledgeChunk).order_by(KnowledgeChunk.id)
        if apply:
            query = query.with_for_update()
        rows = list((await session.scalars(query)).all())
        raw = [sql_dict(r) for r in rows]
        normalized = [dict(r, question=r['questions']) for r in raw]
        english, legacy = split_corpus(normalized, source_chunks())
        keep_ids = {r['id'] for r in english}
        old_ids = {r['id'] for r in legacy}

        def inspect():
            client = m.get_client()
            active = client.query(m.COLLECTION, filter='id >= 0', output_fields=['id', 'question', 'answer', 'section_path', 'content_type', 'category'], limit=16383, consistency_level='Strong')
            if len(active) != len(english) or {r['id'] for r in active} != keep_ids:
                raise ValueError('Active index membership differs from the English corpus; cleanup aborted')
            expected = {r['id']: identity(r) for r in english}
            if any(identity(r) != expected[r['id']] for r in active):
                raise ValueError('Active index content differs from SQL; cleanup aborted')
            historical = []
            exists = client.has_collection('knowledge')
            if exists:
                historical = client.query('knowledge', filter='id >= 0', output_fields=['id', 'dense', 'text', 'question', 'answer', 'section_path', 'content_type', 'category'], limit=16383, consistency_level='Strong')
                if {r['id'] for r in historical} != old_ids or len(historical) != len(legacy):
                    raise ValueError('Legacy collection contains unexpected records; cleanup aborted')
                old = {r['id']: identity(r) for r in legacy}
                if any(identity(r) != old[r['id']] for r in historical):
                    raise ValueError('Legacy index content differs from legacy SQL; cleanup aborted')
            return exists, historical

        exists, historical = await m.acall(inspect)
        print(f'Keep {len(english)} English SQL rows and vectors; retire {len(legacy)} Chinese SQL rows and {len(historical)} legacy vectors.')
        if not apply:
            print('Read-only plan. Use --apply to create a local backup and perform cleanup.')
            return
        if not old_ids and not exists:
            print('Already clean; no changes needed.')
            return
        backup = Path('data/runtime/knowledge-backups') / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(json.dumps({'sql': [r for r in raw if r['id'] in old_ids], 'collection': 'knowledge', 'vectors': historical, 'preserved_english_ids': sorted(keep_ids)}, default=str, ensure_ascii=False), encoding='utf-8')
        backup.chmod(0o600)
        # Backup is complete before either store is changed. Never renumber English IDs.
        if exists:
            await m.acall(lambda: m.get_client().drop_collection('knowledge'))
        if old_ids:
            await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.id.in_(old_ids)))
        await session.commit()
        print(f'Cleanup complete. Local recovery backup: {backup}')


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        await run(args.apply)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
