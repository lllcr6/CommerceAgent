import asyncio
import json
import pathlib
import sys

from app.kb import mining

SAMPLES = pathlib.Path(__file__).resolve().parent.parent / "tests/data/mining_samples.json"


async def main() -> int:
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    failures = 0
    for s in samples:
        pairs = await mining.extract_qa([s["conversation"]])
        if s.get("expect_empty"):
            ok = len(pairs) == 0
        else:
            ok = any(s["expect_question_contains"] in p.question for p in pairs)
        failures += not ok
        print(f"{'✅' if ok else '❌'} Extracted {len(pairs)} pairs: {[p.question for p in pairs]}")
    print(f"\nExtraction checks passed: {len(samples) - failures}/{len(samples)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
