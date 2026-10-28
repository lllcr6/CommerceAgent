"""Read classifier dataset, model, metrics, and validation artifacts."""

import json
import pathlib
from datetime import datetime

import httpx
from fastapi import Depends, APIRouter, HTTPException
from pydantic import BaseModel

from app.core import jobs
from app.topic_schema import SEVERITY, TOPIC_NAMES, SCHEMA_VERSION
from app.db import repository

from app.paths import ROBERTA_DIR


from app.topic_schema import require_topic_classifier
router = APIRouter(prefix="/api/acceptance")

ROBERTA = ROBERTA_DIR
REPORTS = ROBERTA / "reports"
DATASET = ROBERTA / "dataset"
MODEL = ROBERTA / "model"
ONNX = ROBERTA / "onnx"
CLASSIFIER = "http://127.0.0.1:8110"


LINEAGE = (
    ("source/scenarios.jsonl", "Scenario families", "Authored requests and topic boundaries", "roberta-corpus"),
    ("source/split_plan.json", "Assign partitions", "Keep each semantic family in one partition before generation", "roberta-dataset"),
    ("source/generation_checkpoint.json", "Generate variants", "Cached expressions inherit their family's fixed partition", "roberta-corpus"),
)
SPLITS = (("train", "Training: fit model weights"), ("val", "Validation: select epoch and threshold"),
          ("test", "Test: final held-out evaluation only"))
MODEL_TRIO = ("model.safetensors", "tokenizer.json", "threshold.json", "model_manifest.json")


def _stat(path: pathlib.Path) -> dict:

    """Return file existence, byte size, modification time, and line counts for Markdown and JSONL."""
    if not path.exists():
        return {"path": str(path), "present": False}
    st = path.stat()
    out = {"path": str(path), "present": True, "bytes": st.st_size,
           "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}


    if path.suffix in (".jsonl", ".md"):
        out["lines"] = sum(1 for line in path.read_text(encoding="utf-8").splitlines()
                           if line.strip())
    return out


def _load_report(name: str, make_target: str) -> dict:

    """Read a saved JSON report, or return a missing state with the corresponding Make target."""
    path = REPORTS / name
    if not path.exists():
        return {"present": False, "make": make_target,
                "hint": f"No report yet. Run make {make_target}."}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"present": False, "make": make_target, "hint": f"Could not read report: {e}"}
    data["present"] = True
    data["make"] = make_target
    return data


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _split_stats() -> dict:

    """Report partition sizes, label counts, and train/validation/test overlap checks."""
    texts: dict[str, set[str]] = {}
    families = {}; groups = {}
    out: dict[str, dict] = {}
    for key, desc in SPLITS:
        rows = _read_jsonl(DATASET / f"{key}.jsonl")
        counts = {n: 0 for n in TOPIC_NAMES}
        multi = 0
        for r in rows:
            labels = r.get("labels") or []
            multi += len(labels) > 1
            for lb in labels:
                if lb in counts:
                    counts[lb] += 1
        texts[key] = {r["text"] for r in rows}
        families[key] = {r['family_id'] for r in rows if r.get('family_id')}
        groups[key] = {r['group_id'] for r in rows if r.get('group_id')}
        out[key] = {"desc": desc, "size": len(rows), "multi_label": multi,
                    "counts": counts, "file": _stat(DATASET / f"{key}.jsonl")}
    leaks = {
        "train_val": len(texts.get("train", set()) & texts.get("val", set())),
        "train_test": len(texts.get("train", set()) & texts.get("test", set())),
        "val_test": len(texts.get("val", set()) & texts.get("test", set())),
    }
    grouped = {f'{a}_{b}': len(families[a] & families[b]) + len(groups[a] & groups[b])
               for a, b in [('train', 'val'), ('train', 'test'), ('val', 'test')]}
    return {"splits": out, "leaks": leaks, "family_group_overlap": grouped,
            "clean": all(v['size'] for v in out.values()) and not any(leaks.values()) and not any(grouped.values()),
            "scope": "Exact text and family/group checks; semantic disjointness is not guaranteed."}


async def _probe_classifier() -> dict:

    """Probe classifier availability without turning an offline service into a page error."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(f"{CLASSIFIER}/healthz")
            r.raise_for_status()
            detail = r.json()
            return {"online": detail.get('schema_version') == SCHEMA_VERSION and detail.get('language') == 'en-US', "detail": detail}
    except Exception as e:
        return {"online": False, "detail": f"{type(e).__name__}: {e}"}


def _threshold_in_use() -> float | None:
    path = MODEL / "threshold.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("threshold")


@router.get("/overview")
async def overview() -> dict:
    ds = _split_stats()
    health = await _probe_classifier()
    evaluation = _load_report('eval_report.json', 'roberta-eval')
    export = _load_report('export_report.json', 'roberta-export')
    scan = _load_report('threshold_scan.json', 'roberta-threshold-scan')
    classify = _load_report('classify_run.json', 'classify-pool')
    model_ok = all((MODEL / name).exists() for name in MODEL_TRIO)
    definitions = [
        ('data', 'Topic dataset', '/acceptance/data', bool(ds['splits']['test']['size']), ds['clean'],
         ' / '.join(str(ds['splits'][k]['size']) for k in ('train','val','test')) + ' train / validation / test',
         'Synthetic draft: independent annotation review is still required.', []),
        ('golden', 'Independent annotation review', '/acceptance/data', False, False,
         'No independently reviewed gold set yet', 'Review the saved annotation sample before making accuracy claims.', []),
        ('train', 'Topic classifier', '/acceptance/data', model_ok, model_ok,
         'Model weights, tokenizer, threshold and provenance', 'Training uses train and validation only.', ['roberta-train']),
        ('export', 'ONNX export and service', None, export.get('present'), export.get('passed') and health['online'],
         f"{export.get('checked', 0)} validation examples checked; service {'online' if health['online'] else 'offline'}",
         'Export parity uses validation data; model and tokenizer metadata are verified at startup.', ['roberta-export','classifier-up','classifier-down']),
        ('eval', 'Held-out test evaluation', '/acceptance/eval', evaluation.get('present'), evaluation.get('red_line_passed'),
         f"Test examples: {evaluation.get('test_size', 0)}", 'Thresholds are selected on validation, never on test.', ['roberta-eval']),
        ('threshold', 'Validation threshold replay', '/acceptance/eval', scan.get('present'), scan.get('consistent'),
         f"Selected threshold: {scan.get('best_threshold', '—')}", 'Reuses one score table across nine thresholds.', ['roberta-threshold-scan']),
        ('matrix', 'Confusion matrices', '/acceptance/eval', evaluation.get('present'), True,
         f"False positives: {evaluation.get('total_fp', 0)}; false negatives: {evaluation.get('total_fn', 0)}",
         'Inspect error direction for each topic.', ['roberta-eval']),
        ('errors', 'Error review', '/acceptance/errors', evaluation.get('present'), True,
         f"{len(evaluation.get('errors', []))} examples to review", 'Check predictions and source annotations independently.', ['roberta-eval']),
        ('classify', 'Batch classification', '/topics', classify.get('present'), classify.get('status') != 'failed',
         f"Last batch: {classify.get('written', 0)} records saved", 'Requires the enabled, verified classifier.', ['classify-pool'])]
    blocks = [dict(key=key, no=i+1, title=title, page=page,
                   status='missing' if not present else 'pass' if ok else 'fail',
                   headline=headline, note=note, jobs=targets)
              for i, (key,title,page,present,ok,headline,note,targets) in enumerate(definitions)]
    passed = sum(b['status'] == 'pass' for b in blocks)
    return dict(blocks=blocks, passed=passed, total=len(blocks), all_pass=passed == len(blocks),
                classifier=health, jobs=jobs.status_all())


@router.get("/eval")
async def eval_detail() -> dict:

    """Return per-topic metrics, target checks, confusion matrices, aggregate scores, and threshold scans."""
    evaluation = _load_report("eval_report.json", "roberta-eval")
    scan = _load_report("threshold_scan.json", "roberta-threshold-scan")
    return {"eval": evaluation, "scan": scan,
            "threshold_in_use": _threshold_in_use(),
            "severity": SEVERITY, "classifier": await _probe_classifier()}


@router.get("/data")
async def data_detail() -> dict:

    """Return dataset lineage, split distributions, overlap checks, and model/export artifacts."""
    lineage = [{"file": f, "stage": stage, "desc": desc, "make": target,
                **_stat(ROBERTA / f)} for f, stage, desc, target in LINEAGE]
    return {
        "lineage": lineage,
        "dataset": _split_stats(),
        "sample_review": _stat(ROBERTA / "reports/review_sample.jsonl"),
        "model": {"files": [_stat(p) for p in sorted(MODEL.glob("*")) if p.is_file()],
                  "threshold": _threshold_in_use(),
                  "threshold_file": _stat(MODEL / "threshold.json"),
                  "trio_ok": all((MODEL / n).exists() for n in MODEL_TRIO)},
        "onnx": {"files": [_stat(p) for p in sorted(ONNX.glob("*")) if p.is_file()],
                 "report": _load_report("export_report.json", "roberta-export")},
        "topic_names": list(TOPIC_NAMES),
    }


@router.get("/errors")
async def errors_detail() -> dict:

    """Return reviewed prediction errors, missed/extra labels, and recurring topic-boundary confusions. Human reviewers choose corrective examples."""
    evaluation = _load_report("eval_report.json", "roberta-eval")
    if not evaluation.get("present"):
        return {"eval": evaluation, "errors": [], "kinds": {}, "pairs": []}
    errors = evaluation.get("errors", [])
    kinds: dict[str, int] = {}
    pairs: dict[tuple[str, str], int] = {}
    for e in errors:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        for miss in e["missed"]:
            for extra in e["extra"]:
                pairs[(miss, extra)] = pairs.get((miss, extra), 0) + 1
    return {
        "eval": {k: evaluation[k] for k in ("ran_at", "test_size", "threshold", "present")},
        "errors": errors,
        "kinds": kinds,
        "matrix_entries": sum(e["matrix_entries"] for e in errors),
        "total_fp": evaluation["total_fp"], "total_fn": evaluation["total_fn"],
        "pairs": [{"missed": m, "grabbed": g, "count": c, "severity": SEVERITY.get(m)}
                  for (m, g), c in sorted(pairs.items(), key=lambda x: -x[1])],

        "recipes": {
            "Missed labels": "Add training examples containing both a main request and a secondary request.",
            "Wrong category": "Add contrasting training examples that clarify the boundary between topics.",
            "Extra labels": "Add negative training examples with similar wording but a different intent.",
        },
    }


@router.get("/service")
async def service() -> dict:
    return {**await _probe_classifier(), "threshold": _threshold_in_use(),
            "onnx_present": (ONNX / "model.onnx").exists()}


class ClassifyIn(BaseModel):
    text: str


@router.post("/classify", dependencies=[Depends(require_topic_classifier)])
async def classify(body: ClassifyIn) -> dict:
    """Classify a question using the configured topic model and return its scores."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Enter a question to classify.")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{CLASSIFIER}/classify", json={"texts": [text]})
            r.raise_for_status()
            payload = r.json()
            if payload.get('schema_version') != SCHEMA_VERSION:
                raise ValueError('Classifier is not serving the expected schema')
            result = payload['results'][0]
            labels = result['labels']
            if not labels or set(labels) - set(TOPIC_NAMES) or ('other' in labels and len(labels) > 1):
                raise ValueError('Invalid classifier labels')
            if set(result['scores']) != set(TOPIC_NAMES): raise ValueError('Invalid classifier scores')
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Classifier service unavailable ({type(e).__name__}). Start the verified classifier export on port 8110.") from e
    threshold = _threshold_in_use()
    scores = sorted(result["scores"].items(), key=lambda x: -x[1])
    return {"text": text, "threshold": threshold, "labels": result["labels"],
            "scores": [{"label": k, "score": v, "hit": k in result["labels"]}
                       for k, v in scores],

            "fallback": bool(threshold is not None and scores
                             and scores[0][1] < threshold)}
