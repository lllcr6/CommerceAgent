"""Read saved retrieval evaluations and manage persistent faithfulness reviews."""

import json
import hashlib
import pathlib

from fastapi import APIRouter, HTTPException, Query

from app.core import jobs
from app.db import repository
from app.schemas.rageval import FaithCaseStatusRequest
from app.kb.evaluation import RELEVANCE_VERSION

from app.paths import RAG_REPORTS_DIR, RAG_EVAL_FILE


router = APIRouter(prefix="/api/rag-eval")

REPORT = RAG_REPORTS_DIR / "rag_eval.json"
TEXT_LOG = REPORT.with_name("rag_eval.txt")
JOB = "eval-rag"
STRATEGIES = ("vector", "bm25", "hybrid", "hybrid_rerank")
BUCKETS = ("A_policy", "B_model", "C_colloquial", "E_multi")


def _read() -> dict | None:
    try:
        return json.loads(REPORT.read_text(encoding="utf-8"))
    except Exception:
        return None


def _stat(path: pathlib.Path) -> dict:
    """Return file existence, byte size, modification time, and line counts for Markdown and JSONL."""
    try:
        st = path.stat()
    except OSError:
        return {"present": False, "bytes": None, "mtime": None}
    import datetime as dt
    return {"present": True, "bytes": st.st_size,
            "mtime": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}


def _best_strategy(report: dict) -> dict:

    """Select the highest overall MRR from the saved strategy results."""
    best, best_mrr = None, -1.0
    for s in STRATEGIES:
        mrr = ((report.get("retrieval") or {}).get(s) or {}).get("overall", {}).get("mrr")
        if mrr is not None and mrr > best_mrr:
            best, best_mrr = s, mrr
    return {"strategy": best, "mrr": best_mrr if best else None}


@router.get("/overview")
async def overview() -> dict:
    report = _read()
    job = {"specs": [jobs.status(JOB), jobs.status("eval-rag-continue")],
           "resume_available": (RAG_REPORTS_DIR / 'checkpoints' / 'current.json').exists(), "artifacts": {
        "json": _stat(REPORT) | {"path": "data/rag/reports/rag_eval.json"},
        "text": _stat(TEXT_LOG) | {"path": "data/rag/reports/rag_eval.txt"},
    }}
    if report is None:
        return {"present": False, "job": job,
                "make": "make eval-rag",
                "hint": "No evaluation results yet. Run an evaluation to compare retrieval quality. "
                        "This usually takes several minutes."}
    dataset_hash = hashlib.sha256(RAG_EVAL_FILE.read_bytes()).hexdigest()
    if (report.get("meta") or {}).get("dataset_sha256") != dataset_hash:
        return {"present": False, "job": job, "make": "make eval-rag",
                "stale": True,
                "hint": "Your knowledge base or evaluation questions have changed. Run a new evaluation to see up-to-date results."}
    gen = report.get("generation")
    return {
        "present": True,
        "relevance": {"current_version": RELEVANCE_VERSION,
                      "report_version": (report.get("meta") or {}).get("relevance_version", "section-match-legacy"),
                      "needs_rerun": (report.get("meta") or {}).get("relevance_version") != RELEVANCE_VERSION},
        "meta": report.get("meta") or {},
        "retrieval": report.get("retrieval") or {},
        "evidence_coverage": report.get("evidence_coverage") or {},
        "generation": gen,
        "generation_done": gen is not None,
        "evaluation_complete": bool((gen or {}).get('completion', {}).get('complete')),


        "read_notes": report.get("read_notes") or {},
        "best": _best_strategy(report),
        "strategies": list(STRATEGIES),
        "buckets": list(BUCKETS),
        "job": job,
    }


def _case_out(r) -> dict:
    return {
        "id": r.id, "eval_id": r.eval_id, "bucket": r.bucket, "query": r.query,
        "strategy": r.strategy, "answer": r.answer, "reason": r.reason,

        "citations": r.citations, "judge_model": r.judge_model,
        "resolution": r.resolution,
        "status": r.status, "seen_count": r.seen_count,

        "reopened": bool(r.resolved_at) and r.status == "unresolved",
        "first_seen_at": r.first_seen_at.isoformat(timespec="seconds") if r.first_seen_at else None,
        "last_seen_at": r.last_seen_at.isoformat(timespec="seconds") if r.last_seen_at else None,
        "resolved_at": r.resolved_at.isoformat(timespec="seconds") if r.resolved_at else None,
    }


def _hallucination(counts: dict, report: dict | None, status_map: dict) -> dict:

    """Compute flagged and human-confirmed rates only over the current run. Include unsupported questions answered without evidence. Report cumulative ledger totals separately."""
    gen = (report or {}).get("generation") or {}
    faith = gen.get("faithfulness") or {}
    graded = sum((v or {}).get("answered") or 0 for v in faith.values())
    refusal = gen.get("refusal") or {}
    absent = refusal.get("total") or 0
    missed = max(0, absent - (refusal.get("correct") or 0))
    evaluated = (graded + absent) or None


    round_ids = [c.get("id") for c in (gen.get("faithfulness_cases") or []) if c.get("id")]
    tally = {"unresolved": 0, "resolved": 0, "dismissed": 0}
    for eid in round_ids:
        st = status_map.get(eid)
        if st in tally:
            tally[st] += 1
    cases_judged, confirmed_cases = len(round_ids), tally["resolved"]
    rate = (lambda n: round(n / evaluated, 4) if evaluated else None)
    return {"evaluated": evaluated, "graded": graded or None, "absent": absent or None,
            "cases_judged": cases_judged, "cases_confirmed": confirmed_cases,
            "pending": tally["unresolved"], "dismissed": tally["dismissed"],
            "refusal_missed": missed,
            "judged": cases_judged + missed, "confirmed": confirmed_cases + missed,
            "judged_rate": rate(cases_judged + missed),
            "confirmed_rate": rate(confirmed_cases + missed),

            "ledger": {"total": sum(counts.values()), **counts}}


@router.get("/faith-cases")
async def faith_cases(status: str | None = None,
                      page: int = Query(1, ge=1),
                      size: int = Query(5, ge=1, le=50)) -> dict:

    """Return paginated persistent faithfulness cases, optionally filtered by state, with unresolved cases first."""
    if status is not None and status not in ("unresolved", "resolved", "dismissed"):
        raise HTTPException(status_code=400, detail="Invalid case status. Use the supported unresolved, resolved, or no-action status value.")
    rows, total, counts = await repository.list_faith_cases(status, page, size)
    status_map = await repository.faith_case_status_map()
    return {"items": [_case_out(r) for r in rows], "total": total, "page": page,
            "size": size, "pages": max(1, -(-total // size)), "counts": counts,
            "hallucination": _hallucination(counts, _read(), status_map)}


@router.post("/faith-cases/{case_id}/status")
async def set_faith_case_status(case_id: int, req: FaithCaseStatusRequest) -> dict:
    """Persist a human review decision. Reopening clears resolution notes and timestamps; API validation requires notes for final decisions."""
    note = (req.resolution or "").strip()
    if req.status != "unresolved" and not note:
        raise HTTPException(
            status_code=400,
            detail="Explain the fix when resolving a case, or explain why no change is needed.")
    row = await repository.set_faith_case_status(case_id, req.status, note or None)
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    return _case_out(row)
