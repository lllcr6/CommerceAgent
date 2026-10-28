"""Persist source-document chunks as pending; run vectorize_kb afterward."""
import asyncio

from app.db import repository
from app.db.base import engine
from app.kb import documents, dualwrite
from app.kb.sources import KB_DIR, SOURCE_TYPES as DOCS


async def main() -> None:

    existing = await repository.count_chunks_by_content_types(set(DOCS.values()))
    if existing:
        print(f"Initial import skipped: {existing} document passages already exist. Use Apply edits for existing sections or paste new content in section 1.")
        return
    total = 0
    for fname, ctype in DOCS.items():
        md = (KB_DIR / fname).read_text(encoding="utf-8")
        chunks = documents.build_chunks(md, content_type=ctype)
        ids = await dualwrite.write_pending(chunks)
        total += len(ids)
        print(f"  {fname}: {len(ids)} passages")
    print(f"Saved {total} passages, pending indexing. Next: click Index pending chunks in section 4.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
