from app.core import embeddings
from app.db import repository
from app.kb import milvus_client
from app.kb.documents import Chunk


async def write_pending(chunks: list[Chunk]) -> list[int]:
    """Persist document chunks in order and link adjacent chunks before indexing."""
    ids: list[int] = []
    for c in chunks:
        cid = await repository.insert_knowledge_chunk(
            c.category, c.questions, c.answer,
            section_path=c.section_path, content_type=c.content_type,
            is_key_clause=c.is_key_clause,
        )
        ids.append(cid)
    for i, cid in enumerate(ids):
        prev_id = ids[i - 1] if i > 0 else None
        next_id = ids[i + 1] if i < len(ids) - 1 else None
        await repository.set_chunk_neighbors(cid, prev_id, next_id)
    return ids


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


async def vectorize_pending(client=None, batch_size: int = 64, collection: str = milvus_client.COLLECTION) -> int:
    """Embed pending chunks, upsert them by database ID, and mark successful writes done. Run all Milvus calls on its dedicated thread."""
    pending = await repository.list_pending_chunks()
    done = 0
    for batch in _batches(pending, batch_size):
        texts = [f"{r.category}\n{r.questions}\n{r.answer}" for r in batch]
        vectors = await embeddings.embed_texts(texts)
        rows = [
            {"id": r.id, "dense": v, "text": t,
             "question": r.questions, "answer": r.answer,
             "section_path": r.section_path or "", "content_type": r.content_type or "",
             "category": r.category or ""}
            for r, v, t in zip(batch, vectors, texts)
        ]

        def work_upsert(rows=rows):
            c = client or milvus_client.get_client()
            milvus_client.ensure_collection(c, collection=collection)
            milvus_client.upsert_vectors(c, rows, collection=collection)
        await milvus_client.acall(work_upsert)
        for r in batch:
            await repository.mark_chunk_vectorized(r.id, str(r.id))
        done += len(batch)
    if done:
        def work_flush():
            c = client or milvus_client.get_client()
            milvus_client.flush(c, collection=collection)
        await milvus_client.acall(work_flush)
    return done
