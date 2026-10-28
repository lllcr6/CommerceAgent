# English topic dataset

Read [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md) before using these files.
[labels.json](labels.json) defines the 17 English topic IDs and boundaries.

- `source/scenarios.jsonl`: authored scenario families and their two anchor expressions.
- `source/split_plan.json`: deterministic family/group assignments selected before generation.
- `source/generation_checkpoint.json`: successful family expressions, generator provenance,
  real provider token usage where returned, and pending generation failures.
- `source/semantic_review.json`: cached cross-family/protected-evaluation comparison decisions.
- `dataset/{train,val,test}.jsonl`: audited exports, with provenance per message.
- `dataset/manifest.json`: release status, exact file hashes, distributions, and family counts.
- `reports/dataset_audit.json`: exclusions, invariants, and lower-similarity review candidates.
- `DATASET_CARD.md`: measured release composition and limitations.

```bash
# Reads existing inputs and prepares/verifies the plan; no model requests.
PYTHONPATH=. uv run python -m scripts.roberta.english_dataset

# Generates only missing family expressions; consumes model API tokens.
# Successful families are reused. Do not run two writers simultaneously.
make roberta-corpus

# Screen likely source/evaluation overlaps; uses model API tokens and reuses decisions.
PYTHONPATH=. uv run python -m scripts.roberta.review_semantics

# Offline audit and export; refuses missing families and changed frozen inputs.
make roberta-dataset

# Validate the frozen release; no model requests, writes, or classifier training.
make roberta-audit
```

The writer uses the configured judge-slot Flash model for data authoring, not for
classifier accuracy measurement. Data is synthetic and awaits independent human
review. Model weights and exported binaries are local generated artifacts and are
excluded from source distribution.

The saved [held-out evaluation](reports/eval_report.md) covers 560 test examples
with a threshold selected on validation data. Its reported micro-F1 is 0.800 and
macro-F1 is 0.767. Several per-topic targets are unmet; these measurements describe
this synthetic split and do not establish production accuracy.

## English classifier pipeline

The default encoder is `FacebookAI/roberta-base`, pinned to revision
`e2da8e2f811d1448a5b465c236feacd80ffbac7b`. First training downloads its
pretrained weights; it does not call a chat/model API. Local ML dependencies use
the locked `ml` dependency group.

```bash
make roberta-audit           # Read-only frozen release checks
make roberta-train           # Train; best validation epoch, then validation threshold scan
make roberta-eval            # Final held-out test evaluation
make roberta-export          # ONNX export + validation-only parity checks
make classifier-up          # Separate inference process on :8110
make roberta-threshold-scan  # Optional replay through that same exported model
```

Training defaults: seed 42, max sequence length 128, batch size 16, up to 8 epochs,
learning rate 2e-5, weight decay 0.01. Early stopping watches validation micro-F1
with patience 2; best weights are retained in memory. Customize epochs, batch
size or seed using `PYTHONPATH=. uv run --group ml python -m scripts.roberta.train
--epochs 8 --batch-size 16 --seed 42`. Add `--local-files-only` to prohibit downloads.

Training, evaluation, threshold replay and serving share one prediction policy:
labels at or above threshold are selected; a recognized topic suppresses `other`;
if no label passes, the highest score is returned. Threshold ties prefer 0.5,
then the closest threshold, then the lower one. Only validation drives selection.
The export uses RoBERTa’s actual padding token/ID and its two named ONNX inputs.

`model/model_manifest.json` binds the English label order, dataset release,
encoder revision, training settings, decision policy and artifact hashes.
The exported manifest additionally binds source-model identity, tokenizer padding
and input names. Artifacts that do not match the manifest are refused. The runtime returns
the English schema and model identity on `/healthz` and `/classify`; batch writes
validate that identity and all returned labels before saving anything.

The classifier remains disabled in the main app until a verified English model
is trained/exported and `TOPIC_CLASSIFIER_ENABLED=true` is deliberately configured.
Dataset/report inspection remains available while classification is disabled.
Do not tune against test errors: doing so retires that test set as an independent
benchmark. Results on this synthetic draft are not production accuracy claims.
