"""Admin metrics: local customer usage, completed RAG run folders, and saved calibration.

Reading this API never runs an evaluation or calls a model. Synthetic Agent
usage is excluded from customer totals. Historical Langfuse reports remain on disk.
"""

import json
import pathlib

from fastapi import APIRouter

from app.config import settings
from app.core import jobs
from app.core.benchmark_state import business_fingerprint
from app.core.confidence import W_KEY, W_MARGIN, W_TOP1, W_VALID

from app.paths import OBSERVABILITY_REPORTS_DIR, RAG_REPORTS_DIR, DATA_DIR


router = APIRouter(prefix="/api/observability")

REPORT_DIR = OBSERVABILITY_REPORTS_DIR
CALIB = REPORT_DIR / "confidence_calibration.json"
CALIB_JOB = "calibrate-confidence"
TREND_LIMIT = 10


def _read(path: pathlib.Path) -> dict | None:

    """Treat a missing or unreadable report as unavailable rather than failing the dashboard."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _block(job: str, make: str, hint: str) -> dict:
    return {"present": False, "status": "missing", "job": jobs.status(job),
            "make": make, "hint": hint}


def _cost_block() -> dict:
    from app.usage_store import intent_report
    try:
        report = intent_report()
    except Exception:
        report = None
    rows = (report or {}).get('rows') or []
    return {'present': bool(rows), 'status': 'ok' if rows else 'missing',
            'meta': (report or {}).get('meta') or {}, 'rows': rows,
            'total_tokens': (report or {}).get('total_tokens', 0),
            'total_requests': (report or {}).get('total_requests', 0),
            'top': rows[0] if rows else None, 'read_note': None,
            'hint': 'No customer usage recorded yet. New chat requests will appear here automatically. Synthetic Agent tests are excluded.'}


async def _trend_block() -> dict:
    from app.rag_history import completed_runs
    runs = completed_runs(RAG_REPORTS_DIR, TREND_LIMIT)
    partial=[]
    for path in (RAG_REPORTS_DIR/'runs').glob('*/rag_eval.json'):
        report=_read(path) or {}
        if report.get('meta',{}).get('status')=='partial':
            partial.append({'id':path.parent.name, 'skipped':(report.get('generation') or {}).get('skipped')})
    return {'present':bool(runs), 'status':'ok' if runs else 'missing',
            'metric_names':['recall_at_5','precision_at_5','mrr','faithfulness','refusal_rate'],
            'runs':runs, 'partial_runs':partial, 'read_note':None,
            'hint':'No fully completed RAG evaluations yet. This trend updates automatically from retrieval evaluation; interrupted or partially scored runs are excluded.'}


def _calibration_block() -> dict:
    block = _block(CALIB_JOB, "make calibrate-confidence",
                   "No calibration report yet. Run confidence threshold calibration on the evaluation set.")
    block["in_use"] = settings.evidence_confidence_threshold
    block["weights"] = {"top1": W_TOP1, "valid_count": W_VALID,
                        "margin": W_MARGIN, "key_clause": W_KEY}
    report = _read(CALIB)
    if report is None:
        return block
    rec = report.get("recommended") or {}
    scan = report.get("scan") or []
    in_use = settings.evidence_confidence_threshold
    rec_t = rec.get("threshold")

    in_use_stats = next((s for s in scan if s["t"] == round(in_use, 2)), None)
    if rec_t == in_use:
        sync = "match"
    elif in_use > rec_t:
        sync = "conservative"
    else:
        sync = "aggressive"
    return block | {
        "present": True, "status": "ok",
        "meta": report.get("meta") or {},
        "distribution": report.get("distribution") or {},
        "scan": scan,
        "recommended": rec,
        "in_use_stats": in_use_stats,
        "read_note": (report.get("read_notes") or {}).get("confidence_calibration"),
        "in_sync": sync,
    }


def _agent_benchmark():
    report=_read(REPORT_DIR / "agent_benchmark.json")
    if report is not None:
        report['stale']=(report.get('meta',{}).get('business_fingerprint') != business_fingerprint())
        report.pop('cost_scenarios', None)
    return report


@router.get("/overview")
async def overview() -> dict:
    return {"cost": _cost_block(), "trend": await _trend_block(),
            "calibration": _calibration_block(),
            "agent_benchmark": _agent_benchmark(),
            "agent_job": jobs.status("bench-agent"),
            "agent_continue_job": jobs.status("bench-agent-continue") | {
                'resume_available': (DATA_DIR/'benchmarks/agent_runs/current.json').exists()}}
