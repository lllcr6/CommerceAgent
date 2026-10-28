"""Paired BM25/dense/hybrid/hybrid+reranker experiment; no answer generation.

python -m scripts.benchmarks.rag_ablation [--limit 16] [--repeats 3]
One embedding per question per repeat is reused across variants. Reported estimated
standalone latency includes that measured embedding time, not a fictitious cache hit.
Query rewriting/splitting are disabled to isolate retrieval and reranking effects.
"""
import argparse
import asyncio
import math
import random
import time
from collections import defaultdict

from app.config import settings
from app.core import embeddings, rerank
from app.kb import milvus_client as mc
from app.kb.evaluation import check_live_annotations, retrieval_metrics, CHUNKS_FILE, ndcg
from app.paths import RAG_EVAL_FILE
from scripts.eval_rag import _load
from scripts.benchmarks.common import now, paired_delta, sha, summarize, write_report

STRATEGIES = ('bm25','dense','hybrid','hybrid_rerank')


def choose(rows,limit,seed):
    if limit is None: return rows
    buckets=defaultdict(list)
    for r in rows:buckets[r['bucket']].append(r)
    rng=random.Random(seed)
    for values in buckets.values():rng.shuffle(values)
    picked=[]
    while len(picked)<min(limit,len(rows)):
        for bucket in sorted(buckets):
            if buckets[bucket] and len(picked)<limit:picked.append(buckets[bucket].pop())
    return picked


async def main(args):
    all_rows=_load();await check_live_annotations(all_rows)
    rows=choose([q for q in all_rows if not q['should_refuse']],args.limit,args.seed)
    report={'meta':{'created_at':now(),'dataset_sha256':sha(RAG_EVAL_FILE),'chunks_sha256':sha(CHUNKS_FILE),
        'relevance_version':'chunk-id-v1','seed':args.seed,'repeats':args.repeats,'n_questions':len(rows),
        'embed_model':settings.embed_model,'rerank_model':settings.rerank_model,'candidate_k':50,
        'retrieve_k':10,'metric_k':5,'query_splitting':False,'answer_generation':False,
        'protocol':'paired shared embedding; identical hybrid candidates before/after rerank; standalone latency reconstructed from measured stages',
        'cost_note':'No currency claim: embedding/reranking usage is not exposed by these existing wrappers.'},'rows':[]}
    rng=random.Random(args.seed)
    if args.resume:
        import json
        from scripts.benchmarks.common import OUT
        previous=json.loads((OUT/(args.output+'.json')).read_text())
        for key in ('dataset_sha256','chunks_sha256','repeats','embed_model','rerank_model','seed','n_questions','candidate_k','metric_k'):
            if previous['meta'][key] != report['meta'][key]:
                raise ValueError('Cannot resume an experiment with changed '+key)
        report['rows']=previous['rows']
        report['meta']['created_at']=previous['meta']['created_at']
        for record in report['rows']:record.setdefault('load_concurrency',1)
    report['meta']['quality_repeat_concurrency']=args.concurrency
    report['meta']['latency_scope']='Primary latency uses first pass only, at single-worker concurrency. Subsequent repeats only stabilize quality metrics.'
    done={(r['id'],r['repeat']) for r in report['rows']}
    sem=asyncio.Semaphore(args.concurrency)
    first_sem=asyncio.Semaphore(1)
    async def evaluate(q,repeat):
      async with (first_sem if repeat == 0 else sem):
        record={'load_concurrency':1 if repeat == 0 else args.concurrency,'id':q['id'],'bucket':q['bucket'],'repeat':repeat,'relevant_chunk_ids':q['relevant_chunk_ids'],'strategies':{}}
        t=time.perf_counter()
        try:
            vector=await embeddings.embed_query(q['query']);embed_ms=1000*(time.perf_counter()-t)
            def search():
                c=mc.get_client();stages={}
                funcs={'bm25':lambda:mc.bm25_search(c,q['query'],10),
                       'dense':lambda:mc.dense_search(c,vector,10),
                       'hybrid':lambda:mc.hybrid_search(c,vector,q['query'],50,50)}
                names=list(funcs);rng.shuffle(names)
                for name in names:
                    start=time.perf_counter();hits=funcs[name]()
                    stages[name]=(hits,1000*(time.perf_counter()-start))
                return stages
            stages=await mc.acall(search)
            for name,(hits,ms) in stages.items():
                record['strategies'][name]={'ids':[h['id'] for h in hits[:10]],
                    **retrieval_metrics(hits[:10],q),'ndcg':ndcg(hits,set(q['relevant_chunk_ids'])),
                    'measured_search_ms':ms,'standalone_ms':ms+(embed_ms if name!='bm25' else 0)}
            candidates,hybrid_ms=stages['hybrid'];start=time.perf_counter()
            ranked=await rerank.rerank(q['query'],[h['question']+' '+h['answer'] for h in candidates],top_n=10)
            rerank_ms=1000*(time.perf_counter()-start);hits=[candidates[i] for i,_ in ranked]
            record['embedding_ms']=embed_ms;record['rerank_ms']=rerank_ms
            record['strategies']['hybrid_rerank']={'ids':[h['id'] for h in hits],**retrieval_metrics(hits,q),
                'ndcg':ndcg(hits,set(q['relevant_chunk_ids'])),
                'standalone_ms':embed_ms+hybrid_ms+rerank_ms}
        except Exception as exc:
            record['error']=type(exc).__name__ # Never store HTTP headers or provider credentials.
        report['rows'].append(record)
        write_report(args.output,report)
        if len(report['rows'])%10==0:print(f"RAG {len(report['rows'])}/{len(rows)*args.repeats}",flush=True)
    for repeat in range(args.repeats):
        order=list(rows);rng.shuffle(order)
        await asyncio.gather(*(evaluate(q,repeat) for q in order if (q['id'],repeat) not in done))
    complete=[r for r in report['rows'] if not r.get('error') and len(r['strategies'])==4]
    report['summary']={'attempted':len(report['rows']),'complete_pairs':len(complete),
                       'error_rate':1-len(complete)/len(report['rows']),'strategies':{}}
    for strategy in STRATEGIES:
        vals=[r['strategies'][strategy] for r in complete]
        report['summary']['strategies'][strategy]={m:summarize([r[m] for r in vals]) for m in ('recall','precision','mrr','ndcg')}
        latency=[r['strategies'][strategy]['standalone_ms'] for r in complete if r['repeat']==0]
        report['summary']['strategies'][strategy]['standalone_ms']=summarize(latency)
    report['comparisons']={}
    # Average repeated trials within a question before bootstrapping, avoiding pseudoreplication.
    for baseline,variant in [('bm25','hybrid'),('dense','hybrid'),('hybrid','hybrid_rerank'),('dense','hybrid_rerank')]:
        pair={}
        for metric in ('recall','precision','mrr','ndcg'):
            grouped=defaultdict(list)
            for r in complete:grouped[r['id']].append(r)
            if grouped:
                before=[sum(r['strategies'][baseline][metric] for r in group)/len(group) for _,group in sorted(grouped.items())]
                after=[sum(r['strategies'][variant][metric] for r in group)/len(group) for _,group in sorted(grouped.items())]
                pair[metric]=paired_delta(before,after,args.seed)
        report['comparisons'][baseline+' -> '+variant]=pair
    print(write_report(args.output,report),flush=True)
    print(report['summary'],flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--limit',type=int);ap.add_argument('--repeats',type=int,default=1)
    ap.add_argument('--concurrency',type=int,default=1);ap.add_argument('--resume',action='store_true')
    ap.add_argument('--seed',type=int,default=20261021);ap.add_argument('--output',default='rag_ablation')
    args=ap.parse_args()
    if args.repeats<1 or (args.limit is not None and args.limit<1):ap.error('positive limit/repeats required')
    asyncio.run(main(args))
