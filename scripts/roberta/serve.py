"""English topic inference: ONNX Runtime + tokenizers; no PyTorch imports."""
from contextlib import asynccontextmanager
import json
from pathlib import Path
import numpy as np
import onnxruntime as ort
from fastapi import FastAPI
from pydantic import BaseModel
from tokenizers import Tokenizer
import uvicorn
from app.paths import ROBERTA_ONNX_DIR
from app.topic_schema import OTHER_ID, SCHEMA_VERSION, TOPIC_NAMES
from scripts.roberta.inference_lib import apply_threshold, sigmoid
from scripts.roberta.model_contract import sha, validate_artifact


class Runtime:
    def __init__(self, directory):
        directory = Path(directory)
        self.manifest = validate_artifact(directory)
        self.model_id = sha(directory / 'model_manifest.json')
        self.session = ort.InferenceSession(str(directory / 'model.onnx'), providers=['CPUExecutionProvider'])
        self.inputs = [x.name for x in self.session.get_inputs()]
        if self.inputs != self.manifest['input_names'] or set(self.inputs) != {'input_ids', 'attention_mask'}:
            raise ValueError('Incompatible ONNX model inputs')
        self.tokenizer = Tokenizer.from_file(str(directory / 'tokenizer.json'))
        pad_id, pad_token = self.manifest['pad_id'], self.manifest['pad_token']
        if self.tokenizer.token_to_id(pad_token) != pad_id: raise ValueError('Tokenizer padding mismatch')
        self.tokenizer.enable_truncation(max_length=self.manifest['max_length'])
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token=pad_token)
        self.threshold = json.loads((directory / 'threshold.json').read_text())['threshold']

    def classify(self, texts):
        if not texts: return []
        enc = self.tokenizer.encode_batch(texts)
        feed = {'input_ids': np.array([x.ids for x in enc], dtype=np.int64),
                'attention_mask': np.array([x.attention_mask for x in enc], dtype=np.int64)}
        probs = sigmoid(self.session.run(['logits'], feed)[0])
        if probs.shape != (len(texts), len(TOPIC_NAMES)): raise ValueError('Invalid model output dimensions')
        pred = apply_threshold(probs, self.threshold, OTHER_ID)
        return [{'labels': [name for i, name in enumerate(TOPIC_NAMES) if row[i]],
                 'scores': {name: float(score) for name, score in zip(TOPIC_NAMES, scores, strict=True)}}
                for row, scores in zip(pred, probs, strict=True)]


class ClassifyIn(BaseModel):
    texts: list[str]


def create_app(directory=ROBERTA_ONNX_DIR):
    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = Runtime(directory)
        yield
    app = FastAPI(title='Paw & Hearth English topic classifier', lifespan=lifespan)

    @app.get('/healthz')
    def healthz():
        return {'ok': True, 'language': 'en-US', 'schema_version': SCHEMA_VERSION,
                'model_id': app.state.runtime.model_id}

    @app.post('/classify')
    def classify(body: ClassifyIn):
        return {'results': app.state.runtime.classify(body.texts), 'schema_version': SCHEMA_VERSION,
                'model_id': app.state.runtime.model_id}
    return app


app = create_app()
if __name__ == '__main__': uvicorn.run(app, host='127.0.0.1', port=8110)
