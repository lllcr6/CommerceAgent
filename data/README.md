# Project data

Paw & Hearth uses English U.S. pet-supply policies, products, and evaluation cases.

| Directory | Contents |
| --- | --- |
| `rag/knowledge/` | Current English business policies and cat/dog product catalog |
| `rag/evaluation/` | 121 English questions, 69-chunk snapshot, and reviewed chunk-ID annotations |
| `rag/reports/runs/<id>/` | Each RAG experiment's inputs, successful call checkpoints, and report |
| `rag/reports/checkpoints/current.json` | Pointer to the latest RAG experiment |
| `benchmarks/agent_runs/<id>/` | Each Agent experiment's report and private resume credentials |
| `observability/reports/` | Current Agent summary, confidence calibration, and optional local usage exports |
| `roberta/dataset/` | Versioned English topic train/validation/test exports; see `roberta/README.md` |
| `roberta/reports/` | English dataset audits, classifier evaluations, and export reports |
| `runtime/` | Local databases, service PID files, and operational recovery backups |

Run `make eval-check` to validate annotations against the live English index.
`make eval-rag` starts a new experiment; `make eval-rag CONTINUE=1` continues
only the latest experiment and reuses successful calls. Previous experiments remain in `runs/`.
The root `rag_eval.json`, `rag_eval.txt`, and `retrieval_details.json` are latest
report views used by the dashboard.

Metrics use exact chunk IDs: macro Recall@5, Precision@5 with a fixed denominator
of five, and MRR@10. Unsupported questions are scored separately for refusal.
Only fully scored experiments enter the evaluation trend. `make eval-flywheel`
reads this completed history without model calls or a separate evaluation.

`make cost-report DAYS=7` optionally exports local customer input/output token
usage. The dashboard reads local records directly, excluding synthetic tests.
Langfuse is optional for trace inspection.

The English topic dataset is synthetic draft data. Its held-out classifier report is
linked from `roberta/README.md`; these measurements do not establish production
accuracy. Runtime databases, recovery backups, and completed experiments are
independent of source publication.
