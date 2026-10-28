"""Aggregate independent module summaries; an unavailable dependency affects only its own card."""
from fastapi import APIRouter

from app.api import acceptance, kb, observability, rageval
from app.db import repository
from app.config import settings
from app.topic_schema import PENDING

router = APIRouter(prefix="/api/admin")

INTENT_LABELS = {'product_policy': 'Products and policies', 'shipping': 'Shipping', 'order_status': 'Orders', 'return_refund': 'Returns and refunds', 'warranty_support': 'After-sales', 'complaint': 'Complaints', 'human_support': 'Human support', 'chitchat': 'Greetings', 'other': 'Other'}

REVIEW_STATES = ("pending", "approved", "rejected")
RAG_LABEL = {"vector": "Dense", "bm25": "Dense BM25", "hybrid": "Hybrid",
             "hybrid_rerank": "Hybrid + Rerank"}


def _card(key: str, title: str, page: str, lede: str) -> dict:
    """Build one operations dashboard card."""
    return {"key": key, "title": title, "page": page, "lede": lede,
            "status": "error", "headline": "Could not load metrics", "metrics": [], "note": None}


async def _kb_card() -> dict:
    """Summarize database chunks, pending indexing, and search-index consistency."""
    card = _card("kb", "Knowledge base", "/kb",
                 "Documents and reviewed answers → chunks → MySQL and Milvus")
    try:
        stats = await repository.knowledge_stats()
    except Exception as e:
        card["note"] = f"{type(e).__name__}: {e}"
        return card
    milvus = await kb.milvus_state()
    card["metrics"] = [
        {"label": "Saved passages", "value": stats["total"]},
        {"label": "Pending indexing", "value": stats["pending"]},
        {"label": "Milvus", "value": milvus["count"] if milvus["online"] else "Offline"},
        {"label": "Key clauses", "value": stats["key_clause"]},
    ]
    if not stats["total"]:
        card["status"], card["headline"] = "missing", "No knowledge yet. Add a document or build the corpus."
    elif not milvus["online"]:
        card["status"], card["headline"] = "attention", f"SQL rows: {stats['total']} chunks; Milvus is offline"
    elif stats["pending"] or stats["done"] != milvus["count"]:
        card["status"] = "attention"
        card["headline"] = (f"{stats['pending']} chunks pending indexing; "
                            f"SQL indexed rows: {stats['done']}; active Milvus rows: {milvus['count']}")
    else:
        card["status"] = "ok"
        card["headline"] = f"{stats['total']} saved passages; index online and counts match"
    card["note"] = "Content types: " + " ".join(f"{k}={v}" for k, v in stats["by_content_type"].items())
    return card


async def _rageval_card() -> dict:
    """Summarize the saved retrieval report; missing reports are an empty state."""
    card = _card("rageval", "Retrieval evaluation", "/rag-eval",
                 "Compare retrieval ranking, evidence coverage, and answer completeness across four strategies")
    try:
        ov = await rageval.overview()
    except Exception as e:
        card["note"] = f"{type(e).__name__}: {e}"
        return card
    if not ov["present"]:
        card["status"], card["headline"] = "missing", "No current evaluation report. Open retrieval evaluation and run the benchmark."
        card["note"] = "Four strategies across question categories; requires an indexed corpus, Milvus, and a chat model. May take several minutes."
        return card
    best, gen = ov["best"], ov["generation"]
    refusal_rate = ((gen or {}).get("refusal") or {}).get("rate")
    card["metrics"] = [
        {"label": "Best MRR", "value": f"{best['mrr']:.3f}" if best["mrr"] is not None else "—"},
        {"label": "Evaluation set", "value": f"{ov['meta'].get('n_samples', '—')} questions"},
        {"label": "Unsupported refusal rate",
         "value": f"{round(refusal_rate * 100)}%" if refusal_rate is not None else "—"},
    ]
    if not ov["generation_done"]:
        card["status"] = "attention"
        card["headline"] = "Generation evaluation is incomplete. Only retrieval metrics are available; rerun to complete it."
    elif refusal_rate is None or best["mrr"] is None:
        card["status"] = "attention"
        card["headline"] = "Some evaluation metrics are unavailable. Open retrieval evaluation to review the available results."
    else:
        card["status"] = "ok"
        card["headline"] = f"{RAG_LABEL.get(best['strategy'], best['strategy'])} leads; overall MRR {best['mrr']:.3f}"
    card["note"] = f"Last run: {ov['meta'].get('generated_at') or '—'}; displays saved measurements"
    return card


async def _review_card() -> dict:
    """Summarize deduplicated knowledge gaps awaiting human review."""
    card = _card("review", "Knowledge review queue", "/review",
                 "Unanswered questions → Normalize and deduplicate → Human review → Write to knowledge base")
    try:
        counts = {st: len(await repository.list_review_queue(st)) for st in REVIEW_STATES}
    except Exception as e:
        card["note"] = f"{type(e).__name__}: {e}"
        return card
    card["metrics"] = [{"label": {"pending": "Pending review", "approved": "Approved", "rejected": "Rejected"}[st], "value": counts[st]} for st in REVIEW_STATES]
    total = sum(counts.values())
    if not total:
        card["status"], card["headline"] = "missing", "No unanswered questions in the review queue yet."
    elif counts["pending"]:
        card["status"], card["headline"] = "attention", f"{counts['pending']} items awaiting review"
    else:
        card["status"], card["headline"] = "ok", f"No pending reviews; total handled: {total} items"
    card["note"] = "Approved answers are saved and indexed for future retrieval."
    return card


async def _observability_card() -> dict:
    """Summarize available usage, evaluation trends, and confidence calibration."""
    card = _card("observability", "Observability & costs", "/observability",
                 "Cost by intent · Quality trends · Fallback calibration")
    try:
        ov = await observability.overview()
    except Exception as e:
        card["note"] = f"{type(e).__name__}: {e}"
        return card
    cost, trend, calib = ov["cost"], ov["trend"], ov["calibration"]
    latest = (trend["runs"][0]["metrics"] if trend.get("runs") else {}) or {}
    top = cost.get("top")
    card["metrics"] = [

        {"label": "Largest cost share", "value": f"{round(top['share'] * 100)}%" if top else "—"},
        {"label": "Evaluation runs", "value": len(trend.get("runs") or [])},
        {"label": "Faithfulness",
         "value": f"{latest['faithfulness']:.3f}" if latest.get("faithfulness") is not None else "—"},
        {"label": "Active threshold", "value": f"{calib['in_use']:.2f}"},
    ]
    missing = [name for name, blk in (("Cost by intent", cost), ("Evaluation trend", trend),
                                      ("Threshold calibration", calib)) if blk["status"] != "ok"]
    if trend["status"] == "error":
        card["note"] = trend.get("note")
        return card
    if len(missing) == 3:
        card["status"], card["headline"] = "missing", "No measurements yet. Run the corresponding jobs."
    elif missing:
        card["status"], card["headline"] = "attention", "Missing: " + ", ".join(missing)
    elif calib["in_sync"] == "aggressive":
        card["status"] = "attention"
        card["headline"] = (f"Active threshold {calib['in_use']} is below recommended "
                            f"{calib['recommended'].get('threshold')}; unsupported questions may pass")
    else:
        card["status"] = "ok"
        faith = latest.get("faithfulness")
        card["headline"] = ((f"{ INTENT_LABELS.get(top['intent'], top['intent'])} has the highest cost share; " if top else "")
                            + "Latest faithfulness: "
                            + (f"{faith:.3f}" if faith is not None else "—"))
    card["note"] = card["note"] or "Displays saved measurements for the datasets and model configurations recorded in each report."
    return card


async def _topics_card() -> dict:
    if not settings.topic_classifier_enabled:
        return {"key":"topics", "title":"Topics", "page":"/topics",
                "lede":PENDING,"status":"missing","headline":"Classifier disabled","metrics":[],"note":None}
    card = _card("topics", "Topic distribution", "/topics",
                 "Low-confidence questions → Background classification → Most frequent categories,Knowledge gaps to prioritize")
    try:
        dist = await repository.topic_distribution()
    except Exception as e:
        card["note"] = f"{type(e).__name__}: {e}"
        return card
    hit = sum(1 for c in dist["classes"] if c["count"])

    top = sorted((c for c in dist["classes"] if c["count"]),
                 key=lambda c: c["count"], reverse=True)[:3]
    card["metrics"] = [{"label": "Classified questions", "value": dist["total"]},
                       {"label": "Categories represented", "value": f"{hit}/{len(dist['classes'])}"}]
    if not dist["total"]:
        card["status"], card["headline"] = "missing", "No classified questions yet. Run batch classification from classifier validation."
    else:
        card["status"] = "ok"
        card["headline"] = "Top categories: " + ", ".join(f"{c['label']} {c['count']}" for c in top)
    return card


async def _classifier_card() -> dict:
    if not settings.topic_classifier_enabled:
        return {"key":"classifier", "title":"Topic classifier", "page":"/acceptance",
                "lede":PENDING,"status":"missing","headline":"Classifier disabled","metrics":[],"note":None}
    card = _card("classifier", "Classifier validation", "/acceptance",
                 "Corpus → fine-tuning → evaluation → export → background classification; nine acceptance checks")
    try:
        ov = await acceptance.overview()
    except Exception as e:
        card["note"] = f"{type(e).__name__}: {e}"
        return card
    online = ov["classifier"]["online"]
    card["metrics"] = [{"label": "Checks passed", "value": f"{ov['passed']}/{ov['total']}"},
                       {"label": ":8110", "value": "Online" if online else "Offline"}]
    if ov["all_pass"]:
        card["status"], card["headline"] = "ok", "All nine checks passed"
    else:
        missing = [b["title"] for b in ov["blocks"] if b["status"] == "missing"]
        failed = [b["title"] for b in ov["blocks"] if b["status"] == "fail"]
        card["status"] = "attention" if failed else "missing"
        card["headline"] = ", ".join(
            ([f"{len(failed)} checks failed: " + "/".join(failed)] if failed else [])
            + ([f"{len(missing)} artifacts missing: " + "/".join(missing)] if missing else [])
        ) or "Not run yet"
    card["note"] = "Displays the same saved artifacts produced by the command-line jobs"
    return card


@router.get("/overview")
async def overview() -> dict:
    return {"modules": [await _kb_card(), await _rageval_card(), await _review_card(),
                        await _observability_card(), await _topics_card(),
                        await _classifier_card()]}
