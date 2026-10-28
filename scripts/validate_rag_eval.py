"""Validate chunk-ID annotations against the current corpus. Content changes require reviewed annotations before reevaluation."""
import asyncio
import collections
import json
import sys

from app.kb.evaluation import check_live_annotations, load_snapshot, validate_annotations
from app.paths import RAG_EVAL_FILE


def _norm(text: str) -> str:
    return "".join(text.casefold().split())


async def main() -> int:
    rows = [json.loads(line) for line in RAG_EVAL_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    snapshot = load_snapshot()
    try:
        validate_annotations(rows, snapshot)
        if "--offline" not in sys.argv:
            await check_live_annotations(rows)
    except ValueError as error:
        print(f"Annotation validation failed: {error}")
        return 1
    by_id = {chunk["id"]: chunk for chunk in snapshot}
    errors = []
    queries = [row["query"] for row in rows]
    if len(set(queries)) != len(queries):
        errors.append("Duplicate evaluation questions")
    for row in rows:
        if row["should_refuse"]:
            if row["expect_points"]:
                errors.append(f"{row['id']}: Unsupported questions must not have answer points")
            continue
        evidence = _norm("\n".join(by_id[cid]["question"] + ":" + by_id[cid]["answer"]
                                    for cid in row["relevant_chunk_ids"]))
        for point in row["expect_points"]:
            if _norm(point) not in evidence:
                errors.append(f"{row['id']}: Annotated chunks do not contain reference point {point!r}")
    print(f"{len(rows)} questions; categories: {dict(collections.Counter(r['bucket'] for r in rows))}")
    print(f"Snapshot: {len(snapshot)} chunks; " + ("offline validation only; live binding not checked" if "--offline" in sys.argv else "live IDs and fingerprints match"))
    for error in errors:
        print(f"ERROR: {error}")
    print("Per-question relevance annotations validated" if not errors else f"{len(errors)} validation errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
