import asyncio
import datetime as dt
import json
import pathlib
import sys

from scripts.roberta.prelabel import prelabel_batch

from app.paths import ROBERTA_REPORTS_DIR, ROBERTA_DATASET_DIR


GOLDEN = pathlib.Path(__file__).parent / "golden_samples.jsonl"
REPORTS = ROBERTA_REPORTS_DIR
PASS_RATE = 0.8


async def main() -> int:
    manifest=ROBERTA_DATASET_DIR/'manifest.json'
    if manifest.exists() and json.loads(manifest.read_text()).get('language')=='en-US':
        print('No independently reviewed English gold set is configured. Review reports/review_sample.jsonl before enabling a gold-label check.')
        return 1
    samples = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    predicted = await prelabel_batch([s["text"] for s in samples])
    hits = 0
    failures: list[dict] = []
    for s, pred in zip(samples, predicted):
        ok = set(pred) == set(s["labels"])
        hits += ok
        if not ok:
            print(f"✗ {s['text']}\n    Expected: {s['labels']}  Predicted: {pred}")
            failures.append({"text": s["text"], "gold": list(s["labels"]), "pred": list(pred)})
    rate = hits / len(samples)
    print(f"\nGold examples: {len(samples)}; exact matches: {hits}; pass rate: {rate:.0%} (threshold {PASS_RATE:.0%})")
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "golden_report.json").write_text(json.dumps({
        "ran_at": dt.datetime.now().isoformat(timespec="seconds"),
        "total": len(samples), "hits": hits, "rate": round(rate, 4),
        "pass_line": PASS_RATE, "passed": rate >= PASS_RATE, "failures": failures,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if rate >= PASS_RATE else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
