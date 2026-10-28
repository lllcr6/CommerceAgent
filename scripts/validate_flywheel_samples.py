import asyncio
import json
import sys

from app.core.flywheel import normalize_and_match

THRESHOLD = 0.8


async def main():
    samples = json.load(open("tests/data/flywheel_samples.json"))
    passed = 0
    for s in samples:
        try:
            r = await normalize_and_match(s["raw_question"], s["candidates"])
        except Exception as e:
            print(f"✗ {s['raw_question'][:24]}… call failed: {type(e).__name__}")
            continue
        match_ok = r.matched_question_id == s["expect_match"]
        kw_ok = all(k in r.normalized_question for k in s["expect_keywords"])
        ok = match_ok and kw_ok
        passed += ok
        mark = "✓" if ok else "✗"
        print(f"{mark} {s['raw_question'][:24]}… → {r.normalized_question} "
              f"match={r.matched_question_id}(expected {s['expect_match']})")
    rate = passed / len(samples)
    print(f"\nPassed {passed}/{len(samples)} = {rate:.0%} (threshold {THRESHOLD:.0%})")
    return 0 if rate >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
