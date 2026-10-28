"""Publish the completed retrieval benchmark to the existing admin report schema.

Generation/evidence coverage were not measured by this benchmark; never carry
those scores forward from a historical report. Source results remain immutable.
"""
import json
import statistics
from collections import Counter

from app.paths import RAG_REPORTS_DIR, RAG_EVAL_FILE, OBSERVABILITY_REPORTS_DIR
from scripts.benchmarks.common import OUT, sha, load_agent_report


def adapt_rag(report, chunks):
    rows=report['rows'];meta=report['meta']
    if report['summary']['error_rate'] or len(rows)!=meta['n_questions']*meta['repeats']:
        raise ValueError('Publish only a complete, error-free paired retrieval run')
    counts=Counter(r['id'] for r in rows)
    if (len(counts)!=meta['n_questions'] or any(n!=meta['repeats'] for n in counts.values())
            or len({(r['id'],r['repeat']) for r in rows})!=len(rows)):
        raise ValueError('Expected one result per question per repeat')
    retrieval={}
    for name,summary in report['summary']['strategies'].items():
        buckets={}
        for bucket in sorted({r['bucket'] for r in rows}):
            selected=[r for r in rows if r['bucket']==bucket]
            # Each question has the same repeat count; averaging trials equals
            # averaging per-question means. Reject unbalanced inputs.
            grouped={r['id'] for r in selected}
            if len(selected)!=len(grouped)*meta['repeats']:
                raise ValueError('Unbalanced question repeats')
            buckets[bucket]={metric:statistics.mean(r['strategies'][name][metric] for r in selected)
                             for metric in ('recall','precision','mrr','ndcg')}
        buckets['overall']={metric:summary[metric]['mean'] for metric in ('recall','precision','mrr','ndcg')}
        retrieval['vector' if name=='dense' else name]=buckets
    return {'meta':{**meta,'n_samples':meta['n_questions'],'kb_chunks':chunks,
                    'generated_at':meta['created_at'],'recall_k':meta['metric_k'],
                    'chat_model':None,'source_report':'data/benchmarks/rag_ablation.json',
                    'evaluation_scope':'retrieval_only'},
            'retrieval':retrieval,'generation':None,'evidence_coverage':{},
            'read_notes':{'rag_coverage':'Evidence coverage was not measured in this retrieval-only benchmark.'},
            'generation_note':'Answer quality and out-of-scope refusals were not measured in this retrieval-only benchmark.'}


def main():
    source=OUT/'rag_ablation.json';report=json.loads(source.read_text())
    if report['meta']['dataset_sha256']!=sha(RAG_EVAL_FILE):
        raise ValueError('Dataset changed since this benchmark; rerun retrieval evaluation')
    snapshot=RAG_EVAL_FILE.with_name('chunks.json')
    if report['meta']['chunks_sha256']!=sha(snapshot):
        raise ValueError('Chunk snapshot changed since this benchmark')
    adapted=adapt_rag(report,len(json.loads(snapshot.read_text())['chunks']))
    adapted['meta']['source_sha256']=sha(source)
    target=RAG_REPORTS_DIR/'rag_eval.json'
    tmp=target.with_suffix('.json.tmp');tmp.write_text(json.dumps(adapted,ensure_ascii=False,indent=2)+'\n');tmp.replace(target)
    print(target)
    text=target.with_suffix('.txt')
    text.write_text('source_report: data/benchmarks/rag_ablation.json\n'
                    +json.dumps(adapted,ensure_ascii=False,indent=2)+'\n')
    if (OUT/'agent_performance.json').exists():publish_agent()


def publish_agent():
    agent,source_name=load_agent_report()
    payload={'source_report':'data/benchmarks/'+source_name,
             'summary':agent['summary'],'meta':agent['meta'],
             'judge':agent.get('judge'),
             'cohort_provenance':agent.get('cohort_provenance'),
             'outcomes':json.loads((OUT/'agent_outcomes.json').read_text()) if (OUT/'agent_outcomes.json').exists() else None}
    OBSERVABILITY_REPORTS_DIR.mkdir(parents=True,exist_ok=True)
    target=OBSERVABILITY_REPORTS_DIR/'agent_benchmark.json'
    tmp=target.with_suffix('.json.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n');tmp.replace(target)
    print(target)


if __name__=='__main__':main()
