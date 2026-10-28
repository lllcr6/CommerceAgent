"""Validate model artifacts against the configured language, label schema, and integrity checks."""
import hashlib
import json
from pathlib import Path
from app.topic_schema import LABEL2ID, NUM_CLASSES, SCHEMA_VERSION, SCHEMA_SHA256, TOPIC_NAMES
from scripts.roberta.inference_lib import POLICY

BASE = 'FacebookAI/roberta-base'
REVISION = 'e2da8e2f811d1448a5b465c236feacd80ffbac7b'
MAX_LENGTH = 128


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def read_rows(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def encode(samples, tokenizer, max_length=MAX_LENGTH):
    enc = tokenizer([s['text'] for s in samples], truncation=True, padding='max_length', max_length=max_length)
    items = []
    for i, sample in enumerate(samples):
        labels = sample['labels']
        if not labels or len(labels) != len(set(labels)) or set(labels) - LABEL2ID.keys():
            raise ValueError('Invalid English target labels')
        if 'other' in labels and len(labels) != 1: raise ValueError('Other must be exclusive')
        vec = [0.] * NUM_CLASSES
        for label in labels: vec[LABEL2ID[label]] = 1.
        items.append({**{k: enc[k][i] for k in ('input_ids', 'attention_mask')}, 'labels': vec})
    return items


def validate_artifact(directory, dataset=None):
    directory = Path(directory)
    m = json.loads((directory / 'model_manifest.json').read_text())
    if (m.get('schema_version') != SCHEMA_VERSION or m.get('labels_sha256') != SCHEMA_SHA256
            or m.get('labels') != list(TOPIC_NAMES) or m.get('language') != 'en-US'
            or m.get('decision_policy') != POLICY):
        raise ValueError('Incompatible English topic model schema or decision policy')
    if not m.get('files_sha256'): raise ValueError('Missing model artifact integrity hashes')
    for name, digest in m['files_sha256'].items():
        if Path(name).name != name or sha(directory / name) != digest:
            raise ValueError(f'Model artifact changed: {name}')
    config = json.loads((directory / 'config.json').read_text())
    if config.get('model_type') != 'roberta' or config.get('id2label') != {str(i): n for i, n in enumerate(TOPIC_NAMES)}:
        raise ValueError('Model configuration does not match the English labels')
    threshold = json.loads((directory / 'threshold.json').read_text())['threshold']
    if not 0 <= threshold <= 1: raise ValueError('Invalid model threshold')
    if dataset is not None:
        manifest = json.loads((Path(dataset) / 'manifest.json').read_text())
        if m['dataset_manifest_sha256'] != sha(Path(dataset) / 'manifest.json'):
            raise ValueError('Model belongs to a different frozen dataset release')
        for name, digest in manifest['files_sha256'].items():
            if sha(Path(dataset) / name) != digest: raise ValueError(f'Frozen dataset changed: {name}')
    return m


def seal_artifact(directory, manifest):
    directory = Path(directory)
    manifest = dict(manifest)
    manifest['files_sha256'] = {p.name: sha(p) for p in sorted(directory.iterdir())
                               if p.is_file() and p.name != 'model_manifest.json'}
    (directory / 'model_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
