"""English RoBERTa multi-label training. Only train/validation drive decisions."""
import argparse
import json
import numpy as np
from sklearn.metrics import f1_score
from transformers import (AutoModelForSequenceClassification, AutoTokenizer, Trainer,
                          TrainerCallback, TrainingArguments, default_data_collator, set_seed)
from app.topic_schema import ID2LABEL, LABEL2ID, NUM_CLASSES, OTHER_ID, SCHEMA_VERSION, SCHEMA_SHA256, TOPIC_NAMES
from app.paths import ROBERTA_DATASET_DIR, ROBERTA_MODEL_DIR
from scripts.roberta.inference_lib import POLICY, apply_threshold, scan_thresholds, sigmoid
from scripts.roberta.model_contract import BASE, REVISION, MAX_LENGTH, encode, read_rows, seal_artifact, sha


def compute_metrics(eval_pred):
    logits, gold = eval_pred
    pred = apply_threshold(sigmoid(logits), .5, OTHER_ID)
    return {f'{avg}_f1': f1_score(gold, pred, average=avg, zero_division=0) for avg in ('micro', 'macro')}


class BestInMemory(TrainerCallback):
    """Restore the best validation weights; stop after two unimproved epochs."""
    def __init__(self, model, patience=2):
        self.model = model; self.patience = patience
        self.best_metric = -1.; self.best_state = None; self.stale = 0

    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        score = (metrics or {}).get('eval_micro_f1', -1.)
        if score > self.best_metric:
            self.best_metric = score; self.stale = 0
            self.best_state = {k: v.detach().to('cpu', copy=True) for k, v in self.model.state_dict().items()}
        else: self.stale += 1
        if self.stale >= self.patience: control.should_training_stop = True
        return control


def main(args=None):
    if args is None:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--epochs', type=int, default=8)
        parser.add_argument('--batch-size', type=int, default=16)
        parser.add_argument('--seed', type=int, default=42)
        parser.add_argument('--local-files-only', action='store_true')
        args = parser.parse_args()
    from scripts.roberta.validate_dataset import validate
    # Integrity auditing reads hashes/partition metadata; test text is never fed to the model here.
    audit = validate()
    print(f'Frozen English release validated: {audit["counts"]}')
    if args.epochs < 1 or args.batch_size < 1: raise ValueError('Epochs and batch size must be positive')
    set_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(BASE, revision=REVISION, local_files_only=args.local_files_only)
    model = AutoModelForSequenceClassification.from_pretrained(BASE, revision=REVISION,
        local_files_only=args.local_files_only, num_labels=NUM_CLASSES,
        problem_type='multi_label_classification', id2label=ID2LABEL, label2id=LABEL2ID)
    train_ds = encode(read_rows(ROBERTA_DATASET_DIR / 'train.jsonl'), tokenizer)
    val_ds = encode(read_rows(ROBERTA_DATASET_DIR / 'val.jsonl'), tokenizer)
    training_args = TrainingArguments(output_dir=str(ROBERTA_MODEL_DIR.parent / 'training_logs'),
        eval_strategy='epoch', save_strategy='no', learning_rate=2e-5,
        per_device_train_batch_size=args.batch_size, per_device_eval_batch_size=32,
        num_train_epochs=args.epochs, weight_decay=.01, logging_steps=20,
        seed=args.seed, data_seed=args.seed, report_to='none')
    best = BestInMemory(model)
    trainer = Trainer(model=model, args=training_args, train_dataset=train_ds, eval_dataset=val_ds,
        processing_class=tokenizer, data_collator=default_data_collator,
        compute_metrics=compute_metrics, callbacks=[best])
    trainer.train()
    if best.best_state is None: raise RuntimeError('No successful validation epoch; refusing to publish weights')
    model.load_state_dict(best.best_state)
    probs = sigmoid(trainer.predict(val_ds).predictions)
    chosen, scan = scan_thresholds(probs, np.array([r['labels'] for r in val_ds]), OTHER_ID)
    ROBERTA_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    trainer.save_model(ROBERTA_MODEL_DIR); tokenizer.save_pretrained(ROBERTA_MODEL_DIR)
    (ROBERTA_MODEL_DIR / 'threshold.json').write_text(json.dumps({**chosen, 'scan': scan,
        'selected_on': 'val', 'val_sha256': sha(ROBERTA_DATASET_DIR / 'val.jsonl')}, indent=2))
    seal_artifact(ROBERTA_MODEL_DIR, dict(language='en-US', schema_version=SCHEMA_VERSION,
        labels_sha256=SCHEMA_SHA256, labels=list(TOPIC_NAMES), decision_policy=POLICY,
        base_model=BASE, base_revision=REVISION, max_length=MAX_LENGTH, seed=args.seed,
        epochs=args.epochs, batch_size=args.batch_size, learning_rate=2e-5, weight_decay=.01,
        best_validation_micro_f1=best.best_metric, threshold_selection='validation_micro_f1',
        dataset_manifest_sha256=sha(ROBERTA_DATASET_DIR / 'manifest.json'),
        dataset_status='synthetic_draft_requires_independent_review'))
    print(f'English model saved to {ROBERTA_MODEL_DIR}; validation threshold {chosen["threshold"]:.2f}')


if __name__ == '__main__': main()
