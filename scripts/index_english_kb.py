"""Index the knowledge corpus without deleting existing or reviewed knowledge.

Default is a local plan. --publish writes English MySQL rows, embeds only those
rows, and upserts them into knowledge_en_v1. It does not vectorize unrelated
pending records. Repeating the command reuses identical rows. Then bind the
reviewed RAG annotations to the actual IDs with prepare_english_rag --bind-live.
"""
import argparse
import asyncio

from app.kb import milvus_client as m
from app.kb.evaluation import fingerprint
from scripts.prepare_english_rag import source_chunks


async def publish(chunks: list[dict]) -> None:
    from app.core import embeddings
    from app.db import repository
    if m.COLLECTION != 'knowledge_en_v1':
        raise ValueError('English publishing requires MILVUS_COLLECTION=knowledge_en_v1; never overwrite a legacy collection')
    existing = await repository.list_chunks_by_content_types({c['content_type'] for c in chunks})
    by_content = {(r.section_path, r.questions, r.answer, r.content_type, r.category): r.id for r in existing}
    rows = []
    for c in chunks:
        key = (c['section_path'], c['question'], c['answer'], c['content_type'], c['category'])
        cid = by_content.get(key)
        if cid is None:
            cid = await repository.insert_knowledge_chunk(c['category'], c['question'], c['answer'],
                     section_path=c['section_path'], content_type=c['content_type'], is_key_clause=c['is_key_clause'])
            by_content[key] = cid
        rows.append(dict(c,id=cid))
    # Keep document adjacency within each source only, preserving existing rows.
    for i,c in enumerate(rows):
        prev = rows[i-1]['id'] if i and rows[i-1]['source']==c['source'] else None
        nxt = rows[i+1]['id'] if i+1<len(rows) and rows[i+1]['source']==c['source'] else None
        await repository.set_chunk_neighbors(c['id'],prev,nxt)
    for start in range(0,len(rows),16):
        batch = rows[start:start+16]
        texts = [f"{c['category']}\n{c['question']}\n{c['answer']}" for c in batch]
        vectors = await embeddings.embed_texts(texts)
        if len(vectors)!=len(batch):
            raise ValueError('Embedding count mismatch')
        data=[{key:c[key] for key in ('id','question','answer','section_path','content_type','category')}
              | {'dense':v,'text':text} for c,v,text in zip(batch,vectors,texts)]
        def upsert():
            client=m.get_client();m.ensure_collection(client);m.upsert_vectors(client,data);m.flush(client)
        await m.acall(upsert)
        for c in batch:
            await repository.mark_chunk_vectorized(c['id'],str(c['id']))
    print(f'Published {len(rows)} English chunks to {m.COLLECTION}; existing data retained.')
    print('Next: python -m scripts.prepare_english_rag --bind-live; python -m scripts.validate_rag_eval')


async def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish',action='store_true')
    args=parser.parse_args()
    chunks=source_chunks()
    print(f'Plan: {len(chunks)} English chunks -> knowledge_en_v1. No collection will be dropped.')
    if args.publish:
        await publish(chunks)
    else:
        print('Local plan only. Pass --publish to write to MySQL and Milvus and call the embedding provider.')


if __name__=='__main__':
    asyncio.run(main())
