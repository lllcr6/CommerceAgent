"""Compare four retrieval strategies using chunk-ID Recall@5, Precision@5, MRR@10, evidence coverage, judged answer coverage, faithfulness, and unsupported-question refusal. Persist successful work for continuation; missing model calls remain missing."""

import asyncio
import ast
import hashlib
import json
import pathlib
import sys
from datetime import datetime

from pydantic import BaseModel, Field

from app.config import settings
from app.core import model_guard, read_notes, retrieval
from app.core import llm
from app.core.llm import get_chat_model
from app.core.prompts import FAITHFULNESS_PROMPT, RAG_ANSWER_PROMPT
from app.kb import milvus_client
from app.kb.evaluation import (RELEVANCE_VERSION, check_live_annotations, load_snapshot,
                               retrieval_metrics, validate_annotations, CHUNKS_FILE, ndcg)
from app.tools.builtin import faq
from app.kb.eval_checkpoint import Checkpoint, digest, atomic_json
from langchain_core.messages import AIMessage

from app.paths import RAG_EVAL_FILE, RAG_REPORTS_DIR

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT_DIR = RAG_REPORTS_DIR
_OUT_JSON = _OUT_DIR / "rag_eval.json"
_OUT_TXT = _OUT_DIR / "rag_eval.txt"

STRATEGIES = ["vector", "bm25", "hybrid", "hybrid_rerank"]
GRADED_BUCKETS = ["A_policy", "B_model", "C_colloquial", "E_multi"]

STRATEGY_LABEL = {"vector": "Dense", "bm25": "BM25", "hybrid": "Hybrid",
                  "hybrid_rerank": "Hybrid + Rerank"}
BUCKET_LABEL = {"A_policy": "Policy", "B_model": "Model",
                "C_colloquial": "Conversational", "D_absent": "Unsupported", "E_multi": "Multi-source", "overall": "Overall"}
SKIP_GEN = "--skip-gen" in sys.argv
K = 10
RECALL_K = 5
RETR_CONCURRENCY = 5
GEN_CONCURRENCY = 5


CALL_TIMEOUT = 180.0

_retr_sem = asyncio.Semaphore(RETR_CONCURRENCY)
_gen_sem = asyncio.Semaphore(GEN_CONCURRENCY)
_errs: list[str] = []
_checkpoint = None


def _signature(live=None):
    # Only evaluation inputs belong in this identity. Admin jobs, local telemetry,
    # report paths, credentials, and retry bookkeeping must not invalidate scores.
    fields = ['chat_model','chat_base_url','chat_thinking','chat_reasoning_effort','chat_reasoning_split',
              'judge_model','judge_base_url','max_output_tokens','embed_model','embed_base_url',
              'rerank_model','rerank_base_url','milvus_uri','milvus_collection','recall_top_k',
              'rerank_top_k','subquery_split','rerank_min_score','evidence_confidence_threshold']
    config = {k:getattr(settings,k) for k in fields}
    source_root = pathlib.Path(__file__).resolve().parent.parent
    ignored = {'app/core/jobs.py','app/core/observability.py','app/core/generations.py',
               'app/core/benchmark_state.py','app/kb/eval_checkpoint.py'}
    sources = [path for folder in ('app/core', 'app/kb', 'app/tools')
               for path in (source_root / folder).rglob('*.py')
               if str(path.relative_to(source_root)) not in ignored]
    score_names = {'_Faith','_Cov','_norm','_evidence_text','_coverage_mech','_format_evidence',
                   '_deterministic','_gen_one','_refusal_one','_generation'}
    nodes = ast.parse(pathlib.Path(__file__).read_text()).body
    scoring = {n.name:ast.dump(n,include_attributes=False) for n in nodes if getattr(n,'name',None) in score_names}
    return digest({'config': config, 'dataset': RAG_EVAL_FILE.read_text(),
                   'chunks': CHUNKS_FILE.read_text(), 'k': K, 'recall_k': RECALL_K,
                   'strategies':STRATEGIES, 'buckets':GRADED_BUCKETS, 'coverage_prompt':COVERAGE_SYS,
                   'scoring':scoring,
                   'live': sorted(live or [], key=lambda chunk: chunk['id']),
                   'sources': {str(p.relative_to(source_root)): p.read_text() for p in sources}})


def _pack(value):
    if isinstance(value, BaseModel):
        return {'type': type(value).__name__, 'value': value.model_dump(mode='json')}
    return {'type': 'json', 'value': value}


def _unpack(record):
    classes = {'AIMessage': AIMessage, '_Cov': _Cov, '_Faith': _Faith}
    kind = record['type']
    return record['value'] if kind == 'json' else classes[kind].model_validate(record['value'])


class _Faith(BaseModel):
    faithful: bool = Field(description="Whether the answer is faithful to the evidence")
    reason: str = Field(default="")


class _Cov(BaseModel):
    covered_count: int = Field(description="Number of reference points correctly covered by the support answer")


COVERAGE_SYS = """Judge answer coverage. Given the English question, reference points, and support answer, count how many reference points are correctly expressed. Missing, wrong, or invented points do not count. Return an integer covered_count no larger than the reference-point count."""
from langchain_core.prompts import ChatPromptTemplate  # noqa: E402


COVERAGE_PROMPT = ChatPromptTemplate.from_messages(
    [("system", COVERAGE_SYS),
     ("human", "Question: {query}\n\nReference points ({n}):\n{points}\n\nAnswer:\n{answer}")]
)


_LINES: list[str] = []


def _log(msg=""):
    print(msg, flush=True)
    _LINES.append(msg)


def _load():
    samples = [json.loads(ln) for ln in RAG_EVAL_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    validate_annotations(samples, load_snapshot())
    return samples


def _norm(s: str) -> str:
    return "".join((s or "").casefold().split())


def _evidence_text(hits) -> str:
    return "\n".join(f"{h.get('question','')}:{h.get('answer','')}" for h in hits)


def _coverage_mech(points, hits) -> float | None:
    """Check whether normalized reference points occur in the retrieved evidence."""
    if not points:
        return None
    ev = _norm(_evidence_text(hits))
    return sum(1 for p in points if _norm(p) in ev) / len(points)


def _format_evidence(hits) -> str:
    return "\n".join(f"[{i+1}] {h.get('question','')}:{h.get('answer','')}"
                     for i, h in enumerate(hits))


async def _try(factory, label, context=None):
    """Run a coroutine factory with bounded timeout/retry; retain missing results rather than turning failures into zero scores."""
    key = [label, context]
    cached = _checkpoint.get(key) if _checkpoint else None
    if cached is not None:
        return _unpack(cached)
    for i in range(2):
        try:
            result = await asyncio.wait_for(factory(), CALL_TIMEOUT)
        except Exception as e:
            # Keep prompts and provider responses out of logs; identify the exact work item.
            failure = f"{label}: {type(e).__name__}"
            _log(f"Model call failed: {failure} (attempt {i + 1}/2, limit {CALL_TIMEOUT:.0f}s)"
                 + ("; retrying in 2s." if i == 0 else "; left pending for Continue."))
            if i == 0:
                await asyncio.sleep(2.0)
                continue
            _errs.append(failure)
            return None
        # A storage failure must not retry a provider request that already succeeded.
        if _checkpoint and result is not None:
            _checkpoint.put(key, _pack(result))
        return result
    return None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


async def _retrieve(strat, s):
    key = ['retrieve', strat, s['id']]
    cached = _checkpoint.get(key) if _checkpoint else None
    if cached is not None:
        return cached['value']
    async with _retr_sem:
        hits = await retrieval.search_knowledge(s["query"], strategy=strat, top_k=K)
        if _checkpoint:
            _checkpoint.put(key, {'value': hits})
        return hits


async def _deterministic(samples):
    """Return retrieval metrics, evidence coverage, and hits reused by generation."""
    graded = [s for s in samples if s["bucket"] in GRADED_BUCKETS]
    retrieval_out, coverage_out, HITS = {}, {}, {}
    _log("=== Stage 1: retrieval across four strategies and question categories; Recall@%d / Precision / MRR@10 ===" % RECALL_K)
    header = f"{'strategy':16s}" + "".join(f"{b.split('_')[0]:>16s}" for b in GRADED_BUCKETS) + f"{'OVERALL':>16s}"
    _log(header)
    for strat in STRATEGIES:
        hits_list = await asyncio.gather(*(_retrieve(strat, s) for s in graded))
        HITS[strat] = {s["id"]: h for s, h in zip(graded, hits_list)}
        by_bucket, cov_bucket = {}, {}
        row = f"{strat:16s}"
        all_rec, all_prec, all_rr, all_cov, all_ndcg = [], [], [], [], []
        for b in GRADED_BUCKETS:
            idx = [i for i, s in enumerate(graded) if s["bucket"] == b]
            scores = [retrieval_metrics(hits_list[i], graded[i], RECALL_K) for i in idx]
            ndcgs = [ndcg(hits_list[i],set(graded[i]["relevant_chunk_ids"]),RECALL_K) for i in idx]
            covs = [_coverage_mech(graded[i]["expect_points"], hits_list[i]) for i in idx]
            rec = _mean([score["recall"] for score in scores])
            precision = _mean([score["precision"] for score in scores])
            mrr = _mean([score["mrr"] for score in scores])
            by_bucket[b] = {"recall": round(rec, 3), "precision": round(precision, 3), "mrr": round(mrr, 3), "ndcg": round(_mean(ndcgs),3)}
            cov_bucket[b] = round(_mean(covs), 3)
            all_ndcg += ndcgs
            all_rec += [score["recall"] for score in scores]
            all_prec += [score["precision"] for score in scores]
            all_rr += [score["mrr"] for score in scores]
            all_cov += [c for c in covs if c is not None]
            row += f"  R{rec:.2f}/P{precision:.2f}/M{mrr:.2f}".rjust(16)
        by_bucket["overall"] = {"recall": round(_mean(all_rec), 3), "precision": round(_mean(all_prec), 3), "mrr": round(_mean(all_rr), 3), "ndcg": round(_mean(all_ndcg),3)}
        cov_bucket["overall"] = round(_mean(all_cov), 3)
        retrieval_out[strat] = by_bucket
        coverage_out[strat] = cov_bucket
        row += f"  R{_mean(all_rec):.2f}/P{_mean(all_prec):.2f}/M{_mean(all_rr):.2f}".rjust(16)
        _log(row)

    _log("\n=== Stage 2: evidence coverage (reference points found in the top-%d passages; deterministic text matching) ===" % K)
    header = f"{'strategy':16s}" + "".join(f"{b.split('_')[0]:>12s}" for b in GRADED_BUCKETS) + f"{'OVERALL':>12s}"
    _log(header)
    for strat in STRATEGIES:
        row = f"{strat:16s}" + "".join(f"{coverage_out[strat][b]:>12.2f}" for b in GRADED_BUCKETS)
        row += f"{coverage_out[strat]['overall']:>12.2f}"
        _log(row)
    return retrieval_out, coverage_out, HITS


async def _gen_one(strat, s, HITS, model, cov_judge, faith_judge,
                   cov_prompt, faith_prompt):
    hits = HITS[strat][s["id"]]
    evidence = _format_evidence(hits)
    async with _gen_sem:
        ans = await _try(
            lambda: (RAG_ANSWER_PROMPT | model).ainvoke(
                {"query": s["query"], "evidence": evidence}),
            f"gen:{strat}:{s['id']}", evidence)
        if ans is None:
            return {"strat": strat, "bucket": s["bucket"], "coverage": None,
                    "faithful": None, "guard_hits": []}
        text = ans.content if isinstance(ans.content, str) else str(ans.content)


        guard_hits = []
        bad = model_guard.unsupported_models(text, evidence)
        if bad:
            guard_hits.append({"id": s["id"], "strat": strat, "models": bad, "fixed": False})
            retry = await _try(
                lambda: (RAG_ANSWER_PROMPT | model).ainvoke(
                    {"query": s["query"],
                     "evidence": evidence + "\n\n" + model_guard.repair_hint(bad)}),
                f"guard-retry:{strat}:{s['id']}", [evidence, bad])
            if retry is not None:
                fixed_text = retry.content if isinstance(retry.content, str) else str(retry.content)
                if not model_guard.unsupported_models(fixed_text, evidence):
                    text = fixed_text
                    guard_hits[-1]["fixed"] = True
        cov = await _try(
            lambda: (cov_prompt | cov_judge).ainvoke(
                {"query": s["query"], "n": len(s["expect_points"]),
                 "points": "\n".join(f"{i+1}. {p}" for i, p in enumerate(s["expect_points"])),
                 "answer": text}),
            f"cov:{strat}:{s['id']}", text)
        coverage = None
        if cov is not None and s["expect_points"]:
            coverage = min(cov.covered_count, len(s["expect_points"])) / len(s["expect_points"])
        faithful = None
        faith_detail = None
        if strat == "hybrid_rerank":
            fa = await _try(
                lambda: (faith_prompt | faith_judge).ainvoke(
                    {"evidence": evidence, "answer": text}),
                f"faith:{s['id']}", [evidence, text])
            if fa is not None:
                faithful = bool(fa.faithful)
                if not faithful:


                    faith_detail = {"id": s["id"], "bucket": s["bucket"],
                                    "query": s["query"], "answer": text, "reason": fa.reason,
                                    "citations": [
                                        {"n": i + 1, "chunk_id": h.get("id"),
                                         "section_path": h.get("section_path", ""),
                                         "question": h.get("question", ""),
                                         "answer": h.get("answer", "")}
                                        for i, h in enumerate(hits)]}
    return {"strat": strat, "bucket": s["bucket"], "coverage": coverage,
            "faithful": faithful, "faith_detail": faith_detail,
            "guard_hits": guard_hits}


async def _ledger(cases) -> None:
    """Save faithfulness cases independently; an unavailable review table must not discard evaluation results."""
    if not cases:
        _log("\n-- Faithfulness review queue: no cases flagged in this run; nothing to save. --")
        return
    try:
        from app.db import repository
        new = again = reopened = 0
        for c in cases:
            ledger_key = ['ledger', c]
            if _checkpoint and _checkpoint.get(ledger_key) is not None:
                continue
            _, was_resolved = await repository.upsert_faith_case(
                c["id"], c["bucket"], c["query"], c["answer"], c["reason"],
                citations=c.get("citations"), judge_model=llm.resolve_slot("judge")[0])
            if _checkpoint:
                _checkpoint.put(ledger_key, {'saved': True})
            if was_resolved:
                reopened += 1
        rows, total, counts = await repository.list_faith_cases(None, 1, 1)
        _log(f"\n-- Faithfulness review queue: saved {len(cases)} cases from this run; {total} total records"
             f"(unresolved {counts['unresolved']} · resolved {counts['resolved']} · no action needed {counts['dismissed']})"
             + (f"; {reopened} previously reviewed cases reopened" if reopened else "") + " --")
    except Exception as e:
        _log(f"\n-- Could not save faithfulness cases ({type(e).__name__}); the evaluation report is unaffected. "
             f"Check that sql/006_rag_quality_tables.sql has been applied. --")


async def _refusal_one(s):
    """Evaluate an unsupported question through the application pipeline and retain evidence for incorrect answers."""
    async with _gen_sem:
        out = await _try(lambda: faq.query_faq.ainvoke({"keyword": s["query"]}),
                         f"refuse:{s['id']}")
    if out is None:
        return None
    refused = not out.get("sufficient")
    detail = None
    if not refused:
        cites = out.get("citations") or []
        top = cites[0] if cites else {}
        detail = {"id": s["id"], "query": s["query"],
                  "section_path": top.get("section_path", ""),
                  "evidence": f"{top.get('question', '')}:{top.get('answer', '')}"[:220]}
    return {"refused": refused, "detail": detail}


async def _generation(samples, HITS):
    graded = [s for s in samples if s["bucket"] in GRADED_BUCKETS]
    absent = [s for s in samples if s["bucket"] == "D_absent"]
    model = get_chat_model()


    cov_judge = llm.structured(_Cov, temperature=0, slot="judge")
    faith_judge = llm.structured(_Faith, temperature=0, slot="judge")
    cov_prompt, faith_prompt = COVERAGE_PROMPT, FAITHFULNESS_PROMPT

    _log(f"\n=== Stage 3: answer coverage across four strategies, faithfulness, and unsupported-question refusals (judge: {llm.resolve_slot('judge')[0]}) ===")
    tasks = [_gen_one(strat, s, HITS, model, cov_judge, faith_judge, cov_prompt, faith_prompt)
             for strat in STRATEGIES for s in graded]
    tasks += [_refusal_one(s) for s in absent]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    n_gen = len(STRATEGIES) * len(graded)
    gen_results = [r for r in results[:n_gen] if isinstance(r, dict)]
    raw_refusals = results[n_gen:]
    refusals = [r for r in raw_refusals if isinstance(r, dict) and "refused" in r]

    refusal_skipped = [s["id"] for s, r in zip(absent, raw_refusals)
                       if not (isinstance(r, dict) and "refused" in r)]


    if not refusals and not any(r["coverage"] is not None or r["faithful"] is not None
                                for r in gen_results):
        raise RuntimeError(f"Generation evaluation unavailable: all {len(_errs)} calls failed. Missing results will not be recorded as zero scores.")


    answer_cov = {}
    _log("\n-- Answer coverage: fraction of reference points correctly expressed in generated answers --")
    header = f"{'strategy':16s}" + "".join(f"{b.split('_')[0]:>12s}" for b in GRADED_BUCKETS) + f"{'OVERALL':>12s}"
    _log(header)
    for strat in STRATEGIES:
        by = {}
        allc = []
        for b in GRADED_BUCKETS:
            cs = [r["coverage"] for r in gen_results if r["strat"] == strat and r["bucket"] == b and r["coverage"] is not None]

            by[b] = round(_mean(cs), 3) if cs else None
            allc += cs
        by["overall"] = round(_mean(allc), 3) if allc else None
        answer_cov[strat] = by
        fmt = lambda v: ("         N/A" if v is None else f"{v:>12.2f}")  # noqa: E731
        _log(f"{strat:16s}" + "".join(fmt(by[b]) for b in GRADED_BUCKETS) + fmt(by["overall"]))


    faithfulness = {}
    _log("\n-- Faithfulness: Hybrid + Rerank answers supported by retrieved evidence --")
    for b in GRADED_BUCKETS:
        fs = [r["faithful"] for r in gen_results if r["strat"] == "hybrid_rerank" and r["bucket"] == b and r["faithful"] is not None]
        faithfulness[b] = {"v": round(_mean(fs), 3) if fs else None, "answered": len(fs)}
        shown = "N/A" if not fs else f"{faithfulness[b]['v']:.3f}"
        _log(f"{b:14s} faithfulness={shown} ({len(fs)} questions evaluated)")


    faith_cases = [r["faith_detail"] for r in gen_results if r.get("faith_detail")]
    faith_cases.sort(key=lambda c: c["id"])
    if faith_cases:
        _log(f"\n-- Cases flagged as unfaithful: {len(faith_cases)} → {', '.join(c['id'] for c in faith_cases)} --")
    else:
        _log("\n-- Cases flagged as unfaithful: 0 --")


    correct = sum(1 for r in refusals if r["refused"])

    rate = (correct / len(refusals)) if refusals else None
    shown_rate = "N/A" if rate is None else f"{rate:.3f}"
    _log(f"\n-- Unsupported-question refusal rate = {shown_rate} ({correct}/{len(refusals)} correctly refused; {len(refusals)}/{len(absent)} questions evaluated) --")
    miss_cases = [r["detail"] for r in refusals if r["detail"]]
    miss_cases.sort(key=lambda c: c["id"])
    if miss_cases:
        for c in miss_cases:
            _log(f"   Incorrectly answered unsupported question: {c['id']} | {c['query']} | Retrieved section: {c['section_path']}")
    else:
        _log("   Incorrectly answered unsupported questions: 0")
    if refusal_skipped:
        _log(f"   Not evaluated (failed or timed-out calls): {', '.join(refusal_skipped)}")


    guard_hits = [h for r in gen_results for h in r.get("guard_hits", [])]
    guard = {"hits": len(guard_hits), "fixed": sum(1 for h in guard_hits if h["fixed"]),
             "cases": sorted(guard_hits, key=lambda h: (h["id"], h["strat"]))}
    _log(f"\n-- Model-number guard: {guard['hits']} unsupported-model detections; {guard['fixed']} fixed by rewriting --")
    for h in guard["cases"]:
        _log(f"   {h['id']}({h['strat']}) Unsupported model numbers: {', '.join(h['models'])}"
             f" → {'fixed after rewriting' if h['fixed'] else 'still unsupported after rewriting'}")

    await _ledger(faith_cases)

    return {"answer_coverage": answer_cov, "faithfulness": faithfulness,
            "completion": {"complete": not _errs and len(gen_results) == n_gen
                           and all(r['coverage'] is not None for r in gen_results)
                           and sum(v['answered'] for v in faithfulness.values()) == len(graded)
                           and len(refusals) == len(absent),
                           "expected_answers": n_gen,
                           "coverage_scored": sum(r['coverage'] is not None for r in gen_results),
                           "faithfulness_scored": sum(v['answered'] for v in faithfulness.values()),
                           "refusals_scored": len(refusals)},
            "faithfulness_cases": faith_cases, "model_guard": guard,
            "refusal": {"rate": (round(rate, 3) if rate is not None else None),
                        "total": len(refusals), "correct": correct,
                        "cases": miss_cases, "skipped_ids": refusal_skipped},
            "skipped": len(_errs)}


async def _kb_chunks():
    try:
        def work():
            c = milvus_client.get_client()
            milvus_client.ensure_collection(c)
            return milvus_client.count(c)
        return await milvus_client.acall(work)
    except Exception:
        return "—"


def _labeled(data, pick=None):
    """Render strategy and question-category names for chart-note payloads."""
    return {STRATEGY_LABEL[s]: {BUCKET_LABEL[b]: (pick((data[s].get(b) or {})) if pick
                                                 else (data[s] or {}).get(b))
                                for b in GRADED_BUCKETS + ["overall"]}
            for s in STRATEGIES}


async def _read_notes(retrieval_data, coverage_data, generation_data):
    """Save chart notes with reports; dashboards use fallbacks when notes are unavailable."""
    jobs = {
        "rag_mrr": _labeled(retrieval_data, lambda d: d.get("mrr")),
        "rag_recall": _labeled(retrieval_data, lambda d: d.get("recall")),
        "rag_coverage": _labeled(coverage_data),
    }
    if generation_data:
        jobs["rag_answer_coverage"] = _labeled(generation_data["answer_coverage"])
    async def note(kind, payload):
        key = ['note', kind, payload]
        cached = _checkpoint.get(key) if _checkpoint else None
        if cached is not None:
            return kind, cached['value']
        # Chart descriptions are supplied by the dashboard. Do not spend model
        # calls on optional prose, or delay publishing scores when a note times out.
        return kind, None
    notes = {kind: value for kind, value in await asyncio.gather(
        *(note(kind, payload) for kind, payload in jobs.items())) if value}
    _log(f"\nChart descriptions: {len(notes)} cached notes; remaining charts use dashboard summaries (no model calls).")
    return notes


def _write_report(retrieval_data, coverage_data, generation_data, meta, notes=None):
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _OUT_TXT.write_text("\n".join(_LINES) + "\n", encoding="utf-8")
    report = {"meta": meta, "retrieval": retrieval_data,
              "evidence_coverage": coverage_data, "generation": generation_data,
              "read_notes": notes or {}}
    from app.rag_history import publish
    report['meta']['status'] = ('completed' if (generation_data or {}).get('completion', {}).get('complete') else 'partial')
    details_path = _OUT_DIR / 'retrieval_details.json'
    details = json.loads(details_path.read_text()) if details_path.exists() else None
    if _checkpoint:
        publish(_OUT_DIR, _checkpoint, report, '\n'.join(_LINES) + '\n', details)

    atomic_json(_OUT_JSON, report)


def _prepare_run(run_directory, checkpoint):
    atomic_json(run_directory / 'run.json', {
        'run_id': checkpoint.run_id, 'signature': checkpoint.signature,
        'chat_model':settings.chat_model, 'judge_model':llm.resolve_slot('judge')[0],
        'embed_model':settings.embed_model, 'rerank_model':settings.rerank_model,
        'created_at':datetime.now().isoformat(),
        'parameters': {k:getattr(settings,k) for k in ['recall_top_k','rerank_top_k','subquery_split','rerank_min_score','evidence_confidence_threshold','max_output_tokens']}})
    (run_directory / 'questions.jsonl').write_bytes(RAG_EVAL_FILE.read_bytes())
    (run_directory / 'chunks.json').write_bytes(CHUNKS_FILE.read_bytes())


async def main():
    from app.eval_transport import evaluation_transport
    with evaluation_transport():
        await _main()


async def _main():
    global _checkpoint
    _errs.clear()
    _LINES.clear()
    samples = _load()
    live = await check_live_annotations(samples)
    _checkpoint = Checkpoint(_OUT_DIR / 'checkpoints', _signature(live),
                             resume='--continue' in sys.argv, prepare=_prepare_run)
    _log('Continuing evaluation: successful calls will be reused.' if '--continue' in sys.argv
         else 'Starting a new evaluation; successful calls will be saved for continuation.')
    import collections as _c
    per = _c.Counter(s["bucket"] for s in samples)
    _log(f"Evaluation set: {len(samples)} questions (" + ", ".join(
        f"{BUCKET_LABEL.get(b, b)} {n}" for b, n in per.most_common()) + f"); strategies: {STRATEGIES}")
    _log(f"Retrieval concurrency: {RETR_CONCURRENCY} · Generation concurrency: {GEN_CONCURRENCY} · Per-call timeout: {CALL_TIMEOUT:.0f}s\n")
    retrieval_data, coverage_data, HITS = await _deterministic(samples)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    details = {strategy: [{"id": sample["id"], "query": sample["query"],
                          "relevant_chunk_ids": sample["relevant_chunk_ids"],
                          "retrieved_chunk_ids": [hit["id"] for hit in hits[sample["id"]]],
                          **retrieval_metrics(hits[sample["id"]], sample, RECALL_K)}
                         for sample in samples if sample["bucket"] in GRADED_BUCKETS]
               for strategy, hits in HITS.items()}
    (_OUT_DIR / "retrieval_details.json").write_text(
        json.dumps({"relevance_version": RELEVANCE_VERSION, "strategies": details},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generation_data = None
    if SKIP_GEN:
        _log("\n[Generation skipped] --skip-gen: only retrieval and evidence coverage were evaluated. The dashboard will show generation as incomplete.")
    else:
        try:
            generation_data = await _generation(samples, HITS)
        except Exception as e:
            _log(f"\n[Generation incomplete] {type(e).__name__}: {str(e)[:140]}")
            _log("Retrieval and evidence coverage are complete. Generation results are incomplete; rerun after restoring the model provider.")
    if _errs:
        _log(f"\nNote: {len(_errs)} failed or timed-out model calls were skipped. Scores use successfully evaluated samples only.")
    meta = {"n_samples": len(samples), "kb_chunks": await _kb_chunks(),
            "recall_k": RECALL_K, "precision_k": RECALL_K, "retrieve_k": K,
            "relevance_version": RELEVANCE_VERSION, "mrr_k": K,
            "dataset_sha256": hashlib.sha256(RAG_EVAL_FILE.read_bytes()).hexdigest(),
            "chunks_sha256": hashlib.sha256(CHUNKS_FILE.read_bytes()).hexdigest(),
            "metric_definition": "exact chunk IDs; macro Recall@5, Precision@5 (fixed k denominator), MRR@10 (first relevant rank)",
            "failed_calls": list(_errs),
            "concurrency": GEN_CONCURRENCY, "chat_model": settings.chat_model,
            "embed_model":settings.embed_model,"rerank_model":settings.rerank_model,
            "judge_model": llm.resolve_slot("judge")[0],
            "checkpoint_run_id": _checkpoint.run_id,
            "configuration_signature": _checkpoint.signature,
            "continued": '--continue' in sys.argv,
            "generated_at": datetime.now().astimezone().isoformat(timespec='microseconds')}

    notes = {} if SKIP_GEN else await _read_notes(retrieval_data, coverage_data,
                                                  generation_data)
    meta['checkpoint_reused'] = _checkpoint.reused
    meta['checkpoint_saved'] = _checkpoint.saved
    _write_report(retrieval_data, coverage_data, generation_data, meta, notes)
    _log(f'Checkpoint: {_checkpoint.reused} successful calls reused; {_checkpoint.saved} newly saved.')
    _log(f"\nReports saved: {_OUT_JSON.relative_to(_ROOT)} · {_OUT_TXT.relative_to(_ROOT)}")
    _log("Dashboard: http://localhost:8000/rag-eval (Admin → Retrieval evaluation)")
    _log("Evaluation complete: all required questions were scored." if (generation_data or {}).get('completion', {}).get('complete')
         else "Evaluation finished with missing scores. Continue evaluation to fill missing work; this run is excluded from the completed-run trend.")


if __name__ == "__main__":
    import fcntl
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (_OUT_DIR / '.eval.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit('An evaluation is already running. Wait for it to finish or stop it first.')
        sys.exit(asyncio.run(main()) or 0)
