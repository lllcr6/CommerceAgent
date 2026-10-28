"""Scan confidence thresholds using answerable and unsupported questions; recommend the maximum Youden J separation and save the report."""

import asyncio
import json
import pathlib
import sys
from datetime import datetime

from app.core import read_notes, retrieval
from app.core.confidence import compute_evidence_confidence

from app.paths import OBSERVABILITY_REPORTS_DIR, RAG_EVAL_FILE


_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT_DIR = OBSERVABILITY_REPORTS_DIR
_OUT = _OUT_DIR / "confidence_calibration.txt"
_OUT_JSON = _OUT_DIR / "confidence_calibration.json"
ANSWERABLE = {"A_policy", "B_model", "C_colloquial", "E_multi"}
_SEM = asyncio.Semaphore(8)
_LINES: list[str] = []


def _log(msg=""):
    print(msg, flush=True)
    _LINES.append(msg)


async def _conf(sample) -> tuple[str, float]:
    async with _SEM:
        hits = await retrieval.search_knowledge(sample["query"], strategy="hybrid_rerank")
    return sample["bucket"], compute_evidence_confidence(hits).score


def _dist(name, xs) -> dict | None:

    """Print a distribution and return those same values for the saved report."""
    xs = sorted(xs)
    if not xs:
        return None
    def p(q):
        return xs[min(len(xs) - 1, int(q * len(xs)))]
    stat = {"n": len(xs), "min": round(xs[0], 3), "p25": round(p(.25), 3),
            "p50": round(p(.5), 3), "p75": round(p(.75), 3), "max": round(xs[-1], 3)}
    _log(f"{name:12s} n={stat['n']:3d} min={stat['min']:.3f} p25={stat['p25']:.3f} "
         f"p50={stat['p50']:.3f} p75={stat['p75']:.3f} max={stat['max']:.3f}")
    return stat


async def main():
    samples = [json.loads(ln) for ln in open(RAG_EVAL_FILE, encoding="utf-8")]
    results = await asyncio.gather(*(_conf(s) for s in samples))
    answerable = [c for b, c in results if b in ANSWERABLE]
    absent = [c for b, c in results if b == "D_absent"]

    _log("=== Evidence confidence distribution (Hybrid + Rerank) ===")
    dist = {"answerable": _dist("Answerable", answerable), "absent": _dist("Unsupported", absent)}

    _log("\n=== Threshold scan: answerable pass rate and unsupported pass rate at confidence >= t ===")
    _log(f"{'t':>6s} {'Answerable pass rate':>10s} {'Unsupported pass rate':>10s} {'YoudenJ':>8s}")
    scan, best_t, best_j = [], 0.0, -1.0
    for i in range(5, 96):
        t = i / 100
        tpr = sum(1 for c in answerable if c >= t) / len(answerable)
        fpr = sum(1 for c in absent if c >= t) / len(absent)
        j = tpr - fpr
        scan.append({"t": round(t, 2), "pass_rate": round(tpr, 3),
                     "leak_rate": round(fpr, 3), "youden_j": round(j, 3)})
        if i % 5 == 0 or j > best_j:
            _log(f"{t:6.2f} {tpr:10.3f} {fpr:10.3f} {j:8.3f}")
        if j > best_j:
            best_t, best_j = t, j
    _log(f"\nRecommended evidence_confidence_threshold = {best_t:.2f} (Youden J={best_j:.3f})")
    _log("Review the tradeoff before updating app/config.py. This command does not change the active threshold.")

    pick = next((r for r in scan if r["t"] == round(best_t, 2)), None)
    recommended = {"threshold": round(best_t, 2), "youden_j": round(best_j, 3),
                   "pass_rate": pick["pass_rate"] if pick else None,
                   "leak_rate": pick["leak_rate"] if pick else None}


    def _zh(stat):
        return None if not stat else {"count": stat["n"], "min": stat["min"], "p25": stat["p25"],
                                      "median": stat["p50"], "p75": stat["p75"], "max": stat["max"]}
    note = await read_notes.generate("confidence_calibration", {
        "Evidence confidence distributions": {"Answerable (policy/model/conversational/cross-document)": _zh(dist["answerable"]),
                          "Unsupported": _zh(dist["absent"])},
        "Selected threshold": {"threshold": recommended["threshold"], "Answerable pass rate": recommended["pass_rate"],
                    "Unsupported pass rate": recommended["leak_rate"], "YoudenJ": recommended["youden_j"]},
        "Threshold scan (0.1 increments)": [
            {"threshold": r["t"], "Answerable pass rate": r["pass_rate"], "Unsupported pass rate": r["leak_rate"]}
            for r in scan if round(r["t"] * 10, 3) == int(r["t"] * 10)]})
    _log("\nChart note: " + (note if note else "Unavailable; the dashboard uses its fallback."))

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _OUT.write_text("\n".join(_LINES) + "\n", encoding="utf-8")
    _OUT_JSON.write_text(json.dumps({
        "meta": {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "strategy": "hybrid_rerank", "dataset": "data/rag/evaluation/questions.jsonl",
                 "n_answerable": len(answerable), "n_absent": len(absent)},
        "distribution": dist,
        "scan": scan,
        "recommended": recommended,
        "read_notes": {"confidence_calibration": note} if note else {},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _log(f"Reports saved: {_OUT.relative_to(_ROOT)} and {_OUT_JSON.relative_to(_ROOT)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
