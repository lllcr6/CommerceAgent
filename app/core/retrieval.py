import re

from app.config import settings
from app.core import embeddings, rerank
from app.kb import milvus_client
from app.core.service_errors import KnowledgeServiceError

async def _search_database(work):
    try:
        return await milvus_client.acall(work)
    except Exception as exc:
        raise KnowledgeServiceError("retrieval") from exc


_CLAUSE = re.compile(r"[,，;；?？。]|(?<=[a-z])\.(?=\s+[A-Z])|\s+(?i:and|also|plus)\s+(?=(?i:what|how|when|who|where|can|does|is|are|do|will|which|could|would|should)\b)")
_MIN_CLAUSE = 4


def split_clauses(query: str) -> list[str]:

    """Split multi-intent questions into retrieval clauses, or retain the original if fewer than two remain. Clause results are reranked and merged so one intent cannot consume every result slot."""
    parts = [p.strip() for p in _CLAUSE.split(query) if len(p.strip()) >= _MIN_CLAUSE]
    return parts if len(parts) >= 2 else [query]


def _merge_round_robin(lists: list[list[dict]]) -> list[dict]:

    """Interleave clause results by chunk ID, keeping the first hit per section before deferred duplicates."""
    out, seen_id, seen_sec, tail = [], set(), set(), []
    for i in range(max((len(x) for x in lists), default=0)):
        for lst in lists:
            if i >= len(lst):
                continue
            h = lst[i]
            key = h.get("id") or (h.get("section_path", ""), h.get("question", ""))
            if key in seen_id:
                continue
            seen_id.add(key)
            sec = h.get("section_path") or ""
            if sec in seen_sec:
                tail.append(h)
            else:
                seen_sec.add(sec)
                out.append(h)
    return out + tail


def arrange_head_tail(items: list) -> list:

    """Place the strongest passage first, the next strongest last, and the remaining passages in between."""
    if len(items) <= 2:
        return items
    return [items[0], *items[2:], items[1]]


async def search_knowledge(
    query: str, strategy: str = "hybrid_rerank", top_k: int | None = None,
    category: str | None = None, client=None, collection: str = milvus_client.COLLECTION,
    bm25_text: str | None = None, split: bool = True,
) -> list[dict]:

    """Return ranked hits for vector, bm25, hybrid, or hybrid_rerank. Synonym expansion changes only bm25_text; dense retrieval and reranking use the normalized query. Keep all synchronous Milvus calls and client creation on its dedicated thread."""
    top_k = top_k or settings.rerank_top_k
    bt = bm25_text or query


    if split and settings.subquery_split:
        clauses = split_clauses(query)
        if len(clauses) >= 2:
            per = [await search_knowledge(c, strategy=strategy, top_k=top_k,
                                          category=category, client=client,
                                          collection=collection, split=False)
                   for c in clauses]
            return _merge_round_robin(per)[:top_k]

    if strategy == "bm25":
        def work():
            c = client or milvus_client.get_client()
            milvus_client.ensure_collection(c, collection=collection)
            return milvus_client.bm25_search(c, bt, top_k, category, collection)
        return await _search_database(work)

    if strategy == "vector":
        vec = await embeddings.embed_query(query)

        def work():
            c = client or milvus_client.get_client()
            milvus_client.ensure_collection(c, collection=collection)
            return milvus_client.dense_search(c, vec, top_k, category, collection)
        return await _search_database(work)


    vec = await embeddings.embed_query(query)

    def work():
        c = client or milvus_client.get_client()
        milvus_client.ensure_collection(c, collection=collection)
        return milvus_client.hybrid_search(
            c, vec, bt, settings.recall_top_k, settings.recall_top_k, category, collection)
    hits = await _search_database(work)

    if strategy == "hybrid":
        return hits[:top_k]


    docs = [f"{h['question']} {h['answer']}" for h in hits]
    ranked = await rerank.rerank(query, docs, top_n=top_k)
    out = []
    for idx, score in ranked:
        h = dict(hits[idx]); h["rerank_score"] = score
        out.append(h)
    return out
