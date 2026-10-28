"""RAG run history is read from saved reports, never by starting an evaluation."""
import hashlib
import json
from pathlib import Path


def atomic(path, data):
    from app.kb.eval_checkpoint import atomic_json
    atomic_json(path, data)


def publish(root, checkpoint, report, text, details=None):
    # Continue replaces this experiment's report; Rerun prepares a separate run.
    runs = (Path(root) / 'runs').resolve()
    run = runs / checkpoint.run_id
    if run.resolve().parent != runs or run.is_symlink() or not run.is_dir():
        raise ValueError('Evaluation experiment is missing or invalid; refusing to create a replacement.')
    atomic(run/'rag_eval.json', report)
    (run/'rag_eval.txt').write_text(text, encoding='utf-8')
    if details is not None:
        atomic(run/'retrieval_details.json', details)


def completed_runs(root, limit=10):
    reports = []
    for path in (Path(root)/'runs').glob('*/rag_eval.json'):
        try:
            report = json.loads(path.read_text())
            meta, gen = report['meta'], report.get('generation') or {}
            if meta.get('status') != 'completed' or not gen.get('completion', {}).get('complete'):
                continue
            selected = report['retrieval']['hybrid_rerank']['overall']
            faith = gen['faithfulness']
            n = sum(v['answered'] for v in faith.values())
            metrics = {'recall_at_5':selected['recall'], 'precision_at_5':selected['precision'],
                       'mrr':selected['mrr'], 'faithfulness':sum(v['v']*v['answered'] for v in faith.values())/n,
                       'refusal_rate':gen['refusal']['rate'], 'relevance_version':meta['relevance_version']}
            comparable = {k:meta.get(k) for k in ['dataset_sha256','relevance_version','chat_model','judge_model','embed_model','rerank_model']}
            reports.append({'id':path.parent.name, 'created_at':meta['generated_at'], 'triggered_by':'RAG evaluation',
                            'dataset_size':meta['n_samples'], 'metrics':metrics,
                            'comparison_key':hashlib.sha256(json.dumps(comparable,sort_keys=True).encode()).hexdigest()})
        except (ValueError, KeyError, TypeError, ZeroDivisionError, OSError):
            continue
    return sorted(reports, key=lambda r:r['created_at'], reverse=True)[:limit]
