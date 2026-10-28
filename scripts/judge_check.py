"""Replay preserved evidence and answers against human faithfulness dispositions without retrieval or regeneration. Return failure when judgments disagree."""
import asyncio
import sys

from app.core import llm
from app.core.prompts import FAITHFULNESS_PROMPT
from app.db import repository
from pydantic import BaseModel, Field

CONCURRENCY = 5


class _Faith(BaseModel):
    faithful: bool = Field(description="Whether the answer is supported by the evidence")
    reason: str = Field(description="One-sentence explanation")


def evidence_from_citations(citations) -> str:
    """Reconstruct the exact numbered evidence supplied to the faithfulness judge."""
    return "\n".join(f"[{c.get('n', i + 1)}] {c.get('question', '')}:{c.get('answer', '')}"
                     for i, c in enumerate(citations or []))


def expected_faithful(status: str) -> bool | None:
    """Map a human disposition to expected faithfulness; unreviewed cases have no gold judgment."""
    return {"resolved": False, "dismissed": True}.get(status)


def gradable(rows) -> list:
    """Select reviewed cases with preserved evidence snapshots."""
    return [r for r in rows
            if expected_faithful(r.status) is not None and (r.citations or [])]


def verdict_row(case_id: str, status: str, faithful: bool | None) -> dict:
    exp = expected_faithful(status)
    return {"id": case_id, "status": status, "expected": exp, "actual": faithful,
            "agree": faithful is not None and faithful == exp}


async def _judge_one(row, judge, sem) -> dict:


    async with sem:
        for attempt in (1, 2):
            try:
                fa = await (FAITHFULNESS_PROMPT | judge).ainvoke(
                    {"evidence": evidence_from_citations(row.citations), "answer": row.answer})
                out = verdict_row(row.eval_id, row.status, bool(fa.faithful))
                out["reason"] = fa.reason
                return out
            except Exception as e:
                err = f"Judge call failed: {type(e).__name__}"
                if attempt == 2:
                    out = verdict_row(row.eval_id, row.status, None)
                    out["reason"] = err
                    return out
                await asyncio.sleep(1)


async def main() -> int:
    rows, total, counts = await repository.list_faith_cases(None, 1, 200)
    cases = gradable(rows)
    if not cases:
        print(f"No reviewed cases with evidence snapshots among {total} ledger entries. Review cases in the retrieval evaluation page first.")
        return 0

    print(f"Judge model: {llm.resolve_slot('judge')[0]}")
    judge = llm.structured(_Faith, temperature=0, slot="judge")
    sem = asyncio.Semaphore(CONCURRENCY)
    outs = await asyncio.gather(*(_judge_one(r, judge, sem) for r in cases))
    outs.sort(key=lambda o: o["id"])

    label = {True: "Faithful", False: "Unsupported", None: "Call failed"}
    print(f"Judge regression: {total} ledger entries, {len(cases)} gradable (review states: {counts})\n")
    print(f"{'Case':6s} {'Review':8s} {'Expected':6s} {'Actual':8s} Result")
    for o in outs:
        print(f"{o['id']:6s} {o['status']:8s} {label[o['expected']]:6s} "
              f"{label[o['actual']]:8s} {'Match' if o['agree'] else 'Mismatch'}")
    agree = sum(1 for o in outs if o["agree"])
    print(f"\nAgreement: {agree}/{len(outs)}({agree / len(outs):.0%})")
    for o in outs:
        if not o["agree"]:
            print(f"  {o['id']} Judge reason: {o['reason']}")
    return 0 if agree == len(outs) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
