# Agent and retrieval evaluations

Current business cases use Paw & Hearth's U.S. policies and cat/dog catalog.

## Agent evaluation

Run `make bench-agent` for a new experiment or `make bench-agent CONTINUE=1` to
continue the latest one. The benchmark uses 12 three-turn scenarios,
repeated three times. The backend must expose the current resumable evaluation
API; a read-only preflight checks this before accounts or experiments are created.

Experiments are stored under `agent_runs/<id>/`. Private test-account credentials
are mode 0600 and are excluded from published reports. Completed conversations
are reused. Pending requests retain their request IDs to recover server results;
a confirmed failed conversation restarts individually. Recovered response timing
is excluded from latency measurements. Lexical checks are diagnostic contracts,
not human-reviewed task-resolution scores.

A separate configured judge reviews each available synthetic conversation against
store documents for task response, supported claims, and visible safety issues.
The administrator dashboard shows each verdict and its reasoning. Order-specific
facts, tool results, and side effects cannot be verified from the recorded tool
names, so the judge may return uncertain. Pass rate excludes uncertain and failed
judge calls; the report shows their counts. Continue reuses judgments whose inputs
and judge configuration are unchanged and retries failed calls. Judge requests
use additional provider credits and are not included in Agent token averages.

Input and output token counts are measured separately. The admin page estimates
cost using the operator's USD rates. Missing usage is not treated as free usage.
Synthetic requests are excluded from customer usage totals. Evaluation requests
consume model API credits; opening reports and reading history do not.

## RAG evaluation

`make eval-rag` starts a new experiment and `make eval-rag CONTINUE=1` fills
missing work in the latest experiment. Successful retrievals, answers, and
judgments are reused. RAG experiments live in `../rag/reports/runs/`.
Only fully scored experiments enter the dashboard trend.

`make bench-rag` runs a separate retrieval-only paired ablation on the current
annotations. It does not measure answer quality or unsupported-question
refusals. Repeat count, dataset size, model names, and scores must come from its
new report.

## Reproduction

```bash
make eval-check
make eval-rag
make eval-rag CONTINUE=1
make bench-agent
make bench-agent CONTINUE=1
```

These are synthetic development cases. Report their scope and sample count
alongside measured results; do not present them as production traffic or proven
staffing savings. Business records and Langfuse traces are not deleted when
report files are removed.
