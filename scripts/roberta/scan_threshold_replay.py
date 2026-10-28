"""Replay the validation-only threshold scan through the matching ONNX service."""
import datetime as dt
import json
import urllib.request
import numpy as np
from app.paths import ROBERTA_DATASET_DIR, ROBERTA_MODEL_DIR, ROBERTA_ONNX_DIR, ROBERTA_REPORTS_DIR
from app.topic_schema import OTHER_ID, SCHEMA_VERSION, TOPIC_NAMES
from scripts.roberta.inference_lib import scan_thresholds
from scripts.roberta.model_contract import read_rows, sha, validate_artifact

SERVICE = 'http://127.0.0.1:8110'


def main():
    validate_artifact(ROBERTA_MODEL_DIR, ROBERTA_DATASET_DIR)
    exported = validate_artifact(ROBERTA_ONNX_DIR, ROBERTA_DATASET_DIR)
    if exported['source_model_manifest_sha256'] != sha(ROBERTA_MODEL_DIR / 'model_manifest.json'):
        raise ValueError('ONNX export belongs to another model')
    health = json.loads(urllib.request.urlopen(SERVICE + '/healthz', timeout=10).read())
    if health.get('schema_version') != SCHEMA_VERSION or health.get('model_id') != sha(ROBERTA_ONNX_DIR / 'model_manifest.json'):
        raise ValueError('Classifier service is not running the current English export')
    rows = read_rows(ROBERTA_DATASET_DIR / 'val.jsonl')
    results = []
    for start in range(0, len(rows), 32):
        request = urllib.request.Request(SERVICE + '/classify', headers={'Content-Type': 'application/json'},
            data=json.dumps({'texts': [r['text'] for r in rows[start:start + 32]]}).encode())
        response = json.loads(urllib.request.urlopen(request, timeout=120).read())
        if response.get('model_id') != health['model_id']: raise ValueError('Model changed during replay')
        batch = response['results']
        if len(batch) != len(rows[start:start + 32]): raise ValueError('Classifier returned wrong batch size')
        results.extend(batch)
    probs = np.array([[r['scores'][name] for name in TOPIC_NAMES] for r in results])
    gold = np.array([[name in r['labels'] for name in TOPIC_NAMES] for r in rows])
    chosen, scan = scan_thresholds(probs, gold, OTHER_ID)
    in_use = json.loads((ROBERTA_MODEL_DIR / 'threshold.json').read_text())['threshold']
    report = dict(ran_at=dt.datetime.now().isoformat(timespec='seconds'), val_size=len(rows), scan=scan,
        best_threshold=chosen['threshold'], best_micro_f1=chosen['micro_f1'], in_use_threshold=in_use,
        consistent=abs(in_use - chosen['threshold']) < 1e-9, model_id=health['model_id'])
    ROBERTA_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (ROBERTA_REPORTS_DIR / 'threshold_scan.json').write_text(json.dumps(report, indent=2))
    print(f'Validation threshold replay: {chosen["threshold"]:.2f}; consistent={report["consistent"]}')


if __name__ == '__main__': main()
