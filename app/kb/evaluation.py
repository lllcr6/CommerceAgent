"""Validate explicit relevance annotations and content snapshots, then compute standard chunk-ID retrieval metrics."""
import hashlib
import json

from app.paths import RAG_EVAL_FILE

RELEVANCE_VERSION = "chunk-id-v1"
CHUNKS_FILE = RAG_EVAL_FILE.with_name("chunks.json")
FINGERPRINT_FIELDS = ("id", "section_path", "question", "answer", "content_type")


def fingerprint(chunk: dict) -> str:
    payload = {key: chunk[key] for key in FINGERPRINT_FIELDS}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def load_snapshot() -> list[dict]:
    snapshot = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    if snapshot.get("schema_version") != RELEVANCE_VERSION:
        raise ValueError("Unsupported chunk annotation snapshot version")
    return snapshot["chunks"]


def validate_annotations(samples: list[dict], chunks: list[dict]) -> None:
    """Require explicit chunk-ID relevance annotations; never fall back to matching section titles."""
    by_id = {chunk["id"]: chunk for chunk in chunks}
    if len(by_id) != len(chunks):
        raise ValueError("Knowledge snapshot contains duplicate chunk IDs")
    seen = set()
    for sample in samples:
        sid = sample["id"]
        if sid in seen:
            raise ValueError(f"Duplicate evaluation question ID: {sid}")
        seen.add(sid)
        ids = sample.get("relevant_chunk_ids")
        if (sample.get("relevance_version") != RELEVANCE_VERSION
                or not isinstance(ids, list)
                or any(type(cid) is not int for cid in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError(f"{sid}: Missing or invalid explicit chunk ID annotations")
        if bool(ids) == bool(sample["should_refuse"]):
            raise ValueError(f"{sid}: Refusal annotation mismatch: answerable questions require relevant chunks; unsupported questions require none")
        if (sample["bucket"] == "D_absent") != sample["should_refuse"]:
            raise ValueError(f"{sid}: Refusal flag and question category mismatch")
        missing = set(ids) - by_id.keys()
        if missing:
            raise ValueError(f"{sid}: Annotations reference missing chunks {sorted(missing)}")
    for chunk in chunks:
        if chunk.get("sha256") != fingerprint(chunk):
            raise ValueError(f"chunk {chunk['id']}: Snapshot content fingerprint mismatch")


def validate_live_chunks(samples: list[dict], snapshot: list[dict], live: list[dict]) -> None:
    """Reject changed IDs, changed text, or unindexed chunks before evaluation."""
    validate_annotations(samples, snapshot)
    expected = {c["id"]: c for c in snapshot}
    actual = {c["id"]: c for c in live}
    referenced = {cid for s in samples for cid in s["relevant_chunk_ids"]}
    stale = [cid for cid in sorted(referenced)
             if cid not in actual or fingerprint(actual[cid]) != expected[cid]["sha256"]]
    if stale:
        raise ValueError(f"Live knowledge and chunk snapshot mismatch: {stale}; review and update the affected annotations and snapshot")


async def check_live_annotations(samples: list[dict]) -> list[dict]:
    from app.kb import milvus_client

    manifest = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    if manifest.get("id_binding") == "offline-canonical":
        raise ValueError("Offline canonical annotations are not bound to the live English index. Run python -m scripts.prepare_english_rag --bind-live after indexing.")
    if manifest.get("collection") != milvus_client.COLLECTION:
        raise ValueError("Snapshot collection does not match the configured retrieval collection")

    def read():
        client = milvus_client.get_client()
        # Read-only: an absent collection is a failure, not a reason to create an empty one.
        return client.query(collection_name=milvus_client.COLLECTION, filter="id >= 0",
                            output_fields=list(FINGERPRINT_FIELDS), limit=16384)

    live = await milvus_client.acall(read)
    validate_live_chunks(samples, load_snapshot(), live)
    return live


def retrieval_metrics(hits: list[dict], sample: dict, k: int = 5, mrr_k: int = 10) -> dict[str, float]:
    """Compute per-question metrics. Precision uses a fixed k denominator; duplicate IDs count once."""
    if k <= 0 or mrr_k <= 0:
        raise ValueError("k and mrr_k must be positive")
    relevant = sample.get("relevant_chunk_ids")
    if not isinstance(relevant, list) or not relevant:
        raise ValueError(f"{sample.get('id')}: Retrieval metrics require nonempty chunk ID annotations")
    gold = set(relevant)
    found = {hit["id"] for hit in hits[:k]} & gold
    first = next((rank for rank, hit in enumerate(hits[:mrr_k], 1) if hit["id"] in gold), None)
    return {"recall": len(found) / len(gold), "precision": len(found) / k,
            "mrr": 1 / first if first else 0.0}


def ndcg(hits, gold, k=5):
    """Binary nDCG with repeated chunk IDs contributing no extra gain."""
    import math
    seen=set();gains=[]
    for hit in hits[:k]:
        cid=hit['id'];gains.append(int(cid in gold and cid not in seen));seen.add(cid)
    ideal=sum(1/math.log2(i+2) for i in range(min(k,len(gold))))
    return sum(g/math.log2(i+2) for i,g in enumerate(gains))/ideal if ideal else 0.
