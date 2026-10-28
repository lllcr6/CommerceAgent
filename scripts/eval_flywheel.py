"""Show completed RAG experiment history without running another evaluation.

The dashboard reads these same experiment reports. No SQL trend table, legacy
trend files, or AI chart descriptions are created. Use make eval-rag to run a
new experiment or make eval-rag CONTINUE=1 to finish the current experiment.
"""
import argparse
import asyncio
import sys

from app.paths import RAG_REPORTS_DIR
from app.rag_history import completed_runs


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    runs = completed_runs(RAG_REPORTS_DIR, args.limit)
    if not runs:
        print('No fully completed RAG evaluations yet. Continue the latest evaluation or start a new one.')
        return 0
    print('=== Completed RAG experiments (newest first) ===')
    for run in runs:
        metrics = run['metrics']
        print(f"{run['id']} | {run['created_at']} | "
              f"Recall@5={metrics['recall_at_5']:.3f} MRR@10={metrics['mrr']:.3f} "
              f"Faithfulness={metrics['faithfulness']:.3f} Refusal={metrics['refusal_rate']:.3f}")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()) or 0)
