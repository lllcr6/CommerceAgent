"""Classify normalized, unclassified questions in batches outside the live conversation path."""

import argparse
import asyncio
import datetime as dt
import json

import httpx

from app.db import repository
from app.topic_schema import TOPIC_NAMES, SCHEMA_VERSION

from app.paths import ROBERTA_REPORTS_DIR


SERVICE = "http://127.0.0.1:8110"
REPORTS = ROBERTA_REPORTS_DIR


def _write_report(status: str, pending: int, written: int, counts: dict) -> None:
    """Save batch-classification status, including empty idempotent reruns."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "classify_run.json").write_text(json.dumps({
        "ran_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": status, "pending": pending, "written": written,
        "counts": dict(sorted(counts.items(), key=lambda x: -x[1])),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


async def main(min_batch: int, force: bool) -> None:
    from app.topic_schema import require_topic_classifier
    require_topic_classifier()
    rows = await repository.list_unclassified_questions(limit=500)
    if not rows:
        print("No questions are waiting for classification")
        _write_report("empty", 0, 0, {})
        return
    if len(rows) < min_batch and not force:
        print(f"Only {len(rows)} pending questions; minimum batch is {min_batch}. Use --force to process them.")
        _write_report("below_batch", len(rows), 0, {})
        return
    async with httpx.AsyncClient(timeout=300) as client:
        health = await client.get(f"{SERVICE}/healthz")
        health.raise_for_status()
        identity = health.json()
        if identity.get('schema_version') != SCHEMA_VERSION or identity.get('language') != 'en-US' or not identity.get('model_id'):
            raise ValueError('Classifier must serve a verified English model')
        r = await client.post(f"{SERVICE}/classify",
                              json={"texts": [x["text"] for x in rows]})
        r.raise_for_status()
        payload = r.json()
        if payload.get('model_id') != identity['model_id'] or payload.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('Classifier model changed during classification')
        results = payload['results']
        if len(results) != len(rows): raise ValueError('Classifier returned an incorrect result count')
        for result in results:
            labels = result['labels']
            if not labels or len(labels) != len(set(labels)) or set(labels) - set(TOPIC_NAMES) or ('other' in labels and len(labels) > 1):
                raise ValueError('Classifier returned invalid English labels')


    n = await repository.insert_topic_classifications(
        [{"question_id": x["question_id"], "labels": res["labels"]}
         for x, res in zip(rows, results, strict=True)])
    counts: dict[str, int] = {}
    for res in results:
        for lb in res["labels"]:
            counts[lb] = counts.get(lb, 0) + 1
    print(f"Classification complete: {n} records saved; "
          + " ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])))
    _write_report("done", len(rows), n, counts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-batch", type=int, default=10, help="Minimum number of pending questions")
    ap.add_argument("--force", action="store_true", help="Process smaller batches")
    a = ap.parse_args()
    asyncio.run(main(a.min_batch, a.force))
