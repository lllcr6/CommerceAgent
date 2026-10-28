"""One multi-label decision policy for training, evaluation and ONNX serving."""
import numpy as np

POLICY = 'threshold-argmax-exclusive-other-v1'


def sigmoid(logits):
    return 1 / (1 + np.exp(-np.clip(np.asarray(logits), -80, 80)))


def apply_threshold(probs: np.ndarray, threshold: float, other_id=None) -> np.ndarray:
    probs = np.asarray(probs)
    if probs.ndim != 2 or probs.shape[1] == 0 or not np.isfinite(probs).all():
        raise ValueError('Expected a finite [batch, classes] probability matrix')
    if not 0 <= threshold <= 1 or (probs < 0).any() or (probs > 1).any():
        raise ValueError('Probabilities and threshold must be in [0, 1]')
    preds = (probs >= threshold).astype(int)
    if other_id is not None:
        if not 0 <= other_id < probs.shape[1]:
            raise ValueError('Invalid other class index')
        recognized = preds.copy()
        recognized[:, other_id] = 0
        preds[recognized.any(axis=1), other_id] = 0
    for r in range(len(preds)):
        if not preds[r].any():
            preds[r, probs[r].argmax()] = 1
    return preds


def scan_thresholds(probs, gold, other_id):
    gold = np.asarray(gold, dtype=bool)
    scan = []
    for t in [round(.30 + .05 * i, 2) for i in range(9)]:
        pred = apply_threshold(probs, t, other_id).astype(bool)
        tp = int((pred & gold).sum()); fp = int((pred & ~gold).sum()); fn = int((~pred & gold).sum())
        score = 2 * tp / max(2 * tp + fp + fn, 1)
        scan.append(dict(threshold=t, micro_f1=score, tp=tp, fp=fp, fn=fn))
    # Deterministic ties prefer the threshold closest to 0.5, then the lower one.
    best = max(scan, key=lambda r: (r['micro_f1'], -abs(r['threshold'] - .5), -r['threshold']))
    return best, scan
