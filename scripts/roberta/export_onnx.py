"""Export English RoBERTa; parity checks use validation texts, never test data."""
import datetime as dt
import json
from pathlib import Path
import shutil
import tempfile
import numpy as np
import onnxruntime as ort
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from app.paths import ROBERTA_DATASET_DIR, ROBERTA_MODEL_DIR, ROBERTA_ONNX_DIR, ROBERTA_REPORTS_DIR
from app.topic_schema import OTHER_ID
from scripts.roberta.inference_lib import apply_threshold, sigmoid
from scripts.roberta.model_contract import read_rows, seal_artifact, sha, validate_artifact


class LogitsWrapper(torch.nn.Module):
    def __init__(self, model):
        super().__init__(); self.model = model

    def forward(self, input_ids, attention_mask):
        return self.model(input_ids=input_ids, attention_mask=attention_mask).logits


def export_model(model_dir, output_dir, texts, batch_size=32):
    model_dir, output_dir = Path(model_dir), Path(output_dir)
    manifest = validate_artifact(model_dir)
    if not texts: raise ValueError('Validation texts are required for export parity')
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir, local_files_only=True,
                                                               attn_implementation='eager').eval()
    threshold = json.loads((model_dir / 'threshold.json').read_text())['threshold']
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    # A failed parity check must not overwrite a usable export.
    with tempfile.TemporaryDirectory(dir=output_dir.parent, prefix='.onnx-export-') as temp:
        staging = Path(temp)
        sample = tokenizer(['Where is my order?', 'Can I exchange this dog harness for a larger size?'],
                           padding=True, return_tensors='pt', truncation=True, max_length=manifest['max_length'])
        dynamic = {0: 'batch', 1: 'sequence'}
        torch.onnx.export(LogitsWrapper(model), (sample['input_ids'], sample['attention_mask']),
            str(staging / 'model.onnx'), input_names=['input_ids', 'attention_mask'],
            output_names=['logits'], dynamic_axes={'input_ids': dynamic, 'attention_mask': dynamic,
                                                  'logits': {0: 'batch'}},
            opset_version=17, dynamo=False)
        tokenizer.save_pretrained(staging)
        for name in ['config.json', 'threshold.json']: shutil.copy2(model_dir / name, staging / name)
        reference = AutoModelForSequenceClassification.from_pretrained(model_dir, local_files_only=True,
                                                                       attn_implementation='eager').eval()
        session = ort.InferenceSession(str(staging / 'model.onnx'), providers=['CPUExecutionProvider'])
        mismatch = 0
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                enc = tokenizer(texts[i:i + batch_size], padding=True, truncation=True,
                                max_length=manifest['max_length'], return_tensors='pt')
                feed = {k: enc[k].numpy() for k in ['input_ids', 'attention_mask']}
                expected = reference(**{k: enc[k] for k in feed}).logits.numpy()
                actual = session.run(['logits'], feed)[0]
                if not np.allclose(expected, actual, atol=1e-3, rtol=1e-3):
                    raise ValueError('ONNX logits exceed parity tolerance')
                mismatch += int((apply_threshold(sigmoid(expected), threshold, OTHER_ID) !=
                                 apply_threshold(sigmoid(actual), threshold, OTHER_ID)).any(axis=1).sum())
        if mismatch: raise ValueError(f'ONNX label mismatch on {mismatch} validation examples')
        export_manifest = {k: v for k, v in manifest.items() if k != 'files_sha256'}
        export_manifest.update(source_model_manifest_sha256=sha(model_dir / 'model_manifest.json'),
            input_names=[x.name for x in session.get_inputs()], pad_id=tokenizer.pad_token_id,
            pad_token=tokenizer.pad_token, parity_split='val', parity_checked=len(texts), opset=17)
        seal_artifact(staging, export_manifest)
        output_dir.mkdir(parents=True, exist_ok=True)
        for path in staging.iterdir(): shutil.copy2(path, output_dir / path.name)
    return dict(checked=len(texts), mismatch=mismatch, passed=True, parity_split='val',
                onnx_bytes=(output_dir / 'model.onnx').stat().st_size, opset=17)


def main():
    validate_artifact(ROBERTA_MODEL_DIR, ROBERTA_DATASET_DIR)
    texts = [x['text'] for x in read_rows(ROBERTA_DATASET_DIR / 'val.jsonl')]
    report = export_model(ROBERTA_MODEL_DIR, ROBERTA_ONNX_DIR, texts)
    report['ran_at'] = dt.datetime.now().isoformat(timespec='seconds')
    ROBERTA_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (ROBERTA_REPORTS_DIR / 'export_report.json').write_text(json.dumps(report, indent=2))
    print(f'English ONNX export passed validation parity for {len(texts)} examples.')


if __name__ == '__main__': main()
