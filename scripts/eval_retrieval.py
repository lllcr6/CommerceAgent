import asyncio
import json
import pathlib
import sys

from app.core import retrieval

SAMPLES = pathlib.Path(__file__).resolve().parent.parent / "tests/data/retrieval_samples.json"


async def main() -> int:
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    failures = 0
    for s in samples:
        hits = await retrieval.search_knowledge(s["query"], strategy="vector")
        top = hits[0] if hits else None
        ok = bool(top) and s["expect_answer_contains"] in top["answer"]
        failures += not ok
        detail = f"{top['question']} | {top['answer'][:30]}" if top else "(empty)"
        print(f"{'✅' if ok else '❌'} {s['query']!r} -> {detail}")
    print(f"\nCorrect retrievals: {len(samples) - failures}/{len(samples)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
