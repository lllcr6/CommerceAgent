import json
import pathlib
import sys

import asyncio

from app.api.extract import get_extractor

SAMPLES = pathlib.Path(__file__).parent.parent / "tests/data/extract_samples.json"


async def main() -> int:
    samples = json.loads(SAMPLES.read_text())
    failures = 0
    extractor = get_extractor()
    for i, s in enumerate(samples, 1):
        result = await asyncio.wait_for(extractor.ainvoke({"text": s["text"]}), timeout=60)
        got = result.model_dump(mode="json")
        exp = s["expected"]
        ok = got["order_id"] == exp["order_id"] and got["request_type"] == exp["request_type"]
        status = "PASS" if ok else "FAIL"
        failures += not ok
        print(f"[{status}] #{i} {s['text'][:24]}...")
        print(f"       Expected order_id={exp['order_id']} type={exp['request_type']}")
        print(f"       Actual order_id={got['order_id']} type={got['request_type']} resolution={got['expected_solution']}")
    print(f"\n{len(samples) - failures}/{len(samples)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
