"""Final English held-out evaluation: per-topic metrics, matrices and review errors.
Thresholds and model selection are frozen from validation before test inference.
"""

import datetime as dt
import json

import numpy as np
import torch
from sklearn.metrics import multilabel_confusion_matrix, precision_recall_fscore_support
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.topic_schema import LABEL2ID, NUM_CLASSES, SEVERITY, TOPIC_NAMES, OTHER_ID
from scripts.roberta.inference_lib import apply_threshold
from scripts.roberta.model_contract import validate_artifact

from app.paths import ROBERTA_DATASET_DIR, ROBERTA_MODEL_DIR, ROBERTA_REPORTS_DIR


MODEL_DIR = ROBERTA_MODEL_DIR
TEST = ROBERTA_DATASET_DIR / "test.jsonl"
REPORTS = ROBERTA_REPORTS_DIR
RED_LINES = {"strict": 0.9, "standard": 0.8}   # Planning F1 targets; flexible topics have no target.


def pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def predict(model, tokenizer, texts: list[str], threshold: float, device: str, max_length: int = 128) -> np.ndarray:
    model.eval()
    probs_all = []
    with torch.no_grad():
        for i in range(0, len(texts), 32):
            enc = tokenizer(texts[i:i + 32], truncation=True, padding=True,
                            max_length=max_length, return_tensors="pt").to(device)
            probs_all.append(torch.sigmoid(model(**enc).logits).cpu().numpy())
    return apply_threshold(np.concatenate(probs_all), threshold, OTHER_ID)


def main() -> None:
    manifest = validate_artifact(MODEL_DIR, ROBERTA_DATASET_DIR)
    device = pick_device()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR).to(device)
    threshold = json.loads((MODEL_DIR / "threshold.json").read_text())["threshold"]
    samples = [json.loads(l) for l in TEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    texts = [s["text"] for s in samples]
    gold = np.zeros((len(samples), NUM_CLASSES), dtype=int)
    for i, s in enumerate(samples):
        for lb in s["labels"]:
            gold[i][LABEL2ID[lb]] = 1
    preds = predict(model, tokenizer, texts, threshold, device, manifest["max_length"])

    p, r, f1, support = precision_recall_fscore_support(gold, preds, zero_division=0)
    micro_p, micro_r, micro_f1, _ = precision_recall_fscore_support(
        gold, preds, average="micro", zero_division=0)
    macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(
        gold, preds, average="macro", zero_division=0)
    cms = multilabel_confusion_matrix(gold, preds)

    REPORTS.mkdir(parents=True, exist_ok=True)
    lines = ["# English topic classifier: held-out test evaluation", "",
             f"Test examples: {len(samples)}. Threshold: {threshold} (selected on validation only). Synthetic draft labels; independent review pending.", "",
             f"**micro**: P={micro_p:.3f} R={micro_r:.3f} F1={micro_f1:.3f}  |  "
             f"**macro**: P={macro_p:.3f} R={macro_r:.3f} F1={macro_f1:.3f}", "",
             "## Per-topic metrics (planning targets: strict F1 >= 0.9; standard >= 0.8; flexible: no target)", "",
             "| Topic | Tier | P | R | F1 | Support | Target |",
             "|---|---|---|---|---|---|---|"]
    for i, name in enumerate(TOPIC_NAMES):
        sev = SEVERITY[name]
        # A missing target is not counted as an achieved target.
        line = RED_LINES.get(sev)
        if line is not None:
            flag = f"{line} {'Below target: review data' if f1[i] < line else 'Pass'}"
        else:
            flag = "—"
        lines.append(f"| {name} | {sev} | {p[i]:.3f} | {r[i]:.3f} | {f1[i]:.3f} "
                     f"| {int(support[i])} | {flag} |")
    lines += ["", "## Per-topic confusion matrices (TN FP / FN TP)", ""]
    for i, name in enumerate(TOPIC_NAMES):
        tn, fp = cms[i][0]
        fn, tp = cms[i][1]
        lines.append(f"- **{name}**: TN={tn} FP={fp} FN={fn} TP={tp}")
    (REPORTS / "eval_report.md").write_text("\n".join(lines), encoding="utf-8")

    err = ["# Errors for independent review (check both predictions and source annotations)", ""]
    errors: list[dict] = []
    for i, s in enumerate(samples):
        pred_labels = [TOPIC_NAMES[j] for j in range(NUM_CLASSES) if preds[i][j]]
        if set(pred_labels) != set(s["labels"]):
            err.append(f"- {s['text']}\n  Gold: {s['labels']}  Predicted: {pred_labels}")
            # A replacement contributes both one false negative and one false positive.
            missed = [lb for lb in s["labels"] if lb not in pred_labels]
            extra = [lb for lb in pred_labels if lb not in s["labels"]]
            kind = "Wrong category" if missed and extra else ("Missed labels" if missed else "Extra labels")
            errors.append({"text": s["text"], "gold": list(s["labels"]), "pred": pred_labels,
                           "missed": missed, "extra": extra, "kind": kind,
                           "matrix_entries": len(missed) + len(extra)})
    (REPORTS / "error_samples.md").write_text("\n".join(err), encoding="utf-8")

    report = {
        "language": "en-US", "schema_version": manifest["schema_version"],
        "dataset_manifest_sha256": manifest["dataset_manifest_sha256"],
        "dataset_status": manifest["dataset_status"],
        "ran_at": dt.datetime.now().isoformat(timespec="seconds"),
        "test_size": len(samples),
        "threshold": threshold,
        "red_lines": RED_LINES,
        "micro": {"p": round(float(micro_p), 4), "r": round(float(micro_r), 4),
                  "f1": round(float(micro_f1), 4)},
        "macro": {"p": round(float(macro_p), 4), "r": round(float(macro_r), 4),
                  "f1": round(float(macro_f1), 4)},
        "classes": [
            {"name": name, "severity": SEVERITY[name],
             "p": round(float(p[i]), 4), "r": round(float(r[i]), 4),
             "f1": round(float(f1[i]), 4), "support": int(support[i]),
             "red_line": RED_LINES.get(SEVERITY[name]),
             # No target means no pass/fail assertion.
             "passed": (None if SEVERITY[name] not in RED_LINES
                        else bool(f1[i] >= RED_LINES[SEVERITY[name]])),
             "tn": int(cms[i][0][0]), "fp": int(cms[i][0][1]),
             "fn": int(cms[i][1][0]), "tp": int(cms[i][1][1])}
            for i, name in enumerate(TOPIC_NAMES)
        ],
        "errors": errors,
    }
    report["total_cells"] = len(samples) * NUM_CLASSES
    report["total_fp"] = sum(c["fp"] for c in report["classes"])
    report["total_fn"] = sum(c["fn"] for c in report["classes"])
    report["red_line_passed"] = all(c["passed"] is not False for c in report["classes"])
    (REPORTS / "eval_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"micro-F1 {micro_f1:.4f} / macro-F1 {macro_f1:.4f};"
          f"Reports and error samples saved to  {REPORTS}/(.md + .json)")


if __name__ == "__main__":
    main()
