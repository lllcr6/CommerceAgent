"""Authoritative English topic IDs shared by training, reports and serving."""
import hashlib
import json
from app.paths import ROBERTA_DIR

SCHEMA_PATH = ROBERTA_DIR / 'labels.json'
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
SCHEMA_VERSION = SCHEMA['schema_version']
SCHEMA_SHA256 = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
assert SCHEMA['language'] == 'en-US'
assert [x['index'] for x in SCHEMA['labels']] == list(range(17))
TOPIC_NAMES = tuple(x['id'] for x in SCHEMA['labels'])
LABEL2ID = {name: i for i, name in enumerate(TOPIC_NAMES)}
ID2LABEL = dict(enumerate(TOPIC_NAMES))
DISPLAY_NAMES = {x['id']: x['name'] for x in SCHEMA['labels']}
NUM_CLASSES = len(TOPIC_NAMES)
OTHER_ID = LABEL2ID['other']
SEVERITY = {name: ('strict' if i < 5 else 'standard' if i < 13 else 'flexible')
            for i, name in enumerate(TOPIC_NAMES)}


PENDING = 'Topic classification is disabled. Verify the English model and ONNX export, start the classifier service, and enable TOPIC_CLASSIFIER_ENABLED.'

def require_topic_classifier():
    from fastapi import HTTPException
    from app.config import settings
    if not settings.topic_classifier_enabled:
        raise HTTPException(503, PENDING)
