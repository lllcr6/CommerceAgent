"""Versioned English topic data, family-level splits, and offline leakage checks.

No production taxonomy, serving configuration, graph, or evaluation cache is changed.
Only --generate uses the model API; --audit and --export are offline.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

from app.paths import REPO_ROOT, ROBERTA_DIR, ROBERTA_DATASET_DIR, RAG_EVAL_FILE
from app.kb.eval_checkpoint import atomic_json, digest

VERSION = 'paw-topics-en-v1'
SEED = 20261022
SOURCE = ROBERTA_DIR / 'source/scenarios.jsonl'
LABELS = ROBERTA_DIR / 'labels.json'
PLAN = ROBERTA_DIR / 'source/split_plan.json'
CACHE = ROBERTA_DIR / 'source/generation_checkpoint.json'
REPORT = ROBERTA_DIR / 'reports/dataset_audit.json'
STOP = set('a an the i me my we our you your it its is are was were be been being do does did to for of and or on in at as by with from that this these those have has had can could would should will may please hi hello help want need like know tell ask about there how what when where which whether if also just'.split())
ALIASES = {'parcel':'package','parcels':'package','postage':'shipping','refunds':'refund',
           'receipts':'receipt','invoice':'receipt','invoices':'receipt','purchase':'order',
           'purchases':'order','unshipped':'unfulfilled','pending':'unfulfilled','colour':'color',
           'colours':'color','colours':'color','dispatch':'shipping','dispatched':'shipped',
           'kennel':'crate','barrier':'gate','profile':'account','loyalty':'rewards',
           'reward':'rewards','repairing':'repair','servicing':'repair'}


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized(text):
    text = unicodedata.normalize('NFKC', text).casefold().replace('’', "'")
    for old, new in [("can't",'cannot'),("won't",'will not'),("i'd",'i would'),
                     ("i'm",'i am'),("i've",'i have'),("doesn't",'does not'),
                     ("don't",'do not'),("isn't",'is not'),("it's",'it is')]:
        text = text.replace(old, new)
    text = re.sub(r'\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b', ' email ', text)
    text = re.sub(r'\b\d+(?:[.,]\d+)*\b', ' number ', text)
    return ' '.join(re.findall(r'[a-z]+', text))


def words(text):
    return [ALIASES.get(w, w) for w in normalized(text).split() if w not in STOP]


def features(text):
    tokens = words(text)
    result = Counter(tokens)
    result.update({' '.join(pair): 2 for pair in zip(tokens, tokens[1:])})
    return result


def similar_pairs(texts, threshold=.80):
    """Sparse lexical TF-IDF cosine. This is not an embedding/semantic guarantee."""
    bags = [features(t) for t in texts]
    df = Counter(feature for bag in bags for feature in bag)
    vectors = []
    index = defaultdict(list)
    for i, bag in enumerate(bags):
        vector = {k:(1 + math.log(v)) * (1 + math.log((len(bags)+1)/(df[k]+1))) for k,v in bag.items()}
        length = math.sqrt(sum(v*v for v in vector.values())) or 1
        vector = {k:v/length for k,v in vector.items()}
        dots = defaultdict(float)
        for k,v in vector.items():
            for j,previous in index[k]:
                dots[j] += v*previous
        for j,score in dots.items():
            if score >= threshold:
                yield j,i,round(score,6)
        for k,v in vector.items(): index[k].append((i,v))
        vectors.append(vector)


class Groups:
    def __init__(self, ids): self.parent = {x:x for x in ids}
    def find(self, x):
        if self.parent[x] != x: self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    def join(self, a, b):
        a,b=self.find(a),self.find(b)
        self.parent[max(a,b)] = min(a,b)


def protected_questions():
    rows = [{'id':'rag:'+s['id'], 'text':s['query']} for s in read_rows(RAG_EVAL_FILE)]
    cases = json.loads((REPO_ROOT/'data/benchmarks/agent_scenarios.json').read_text())
    for scenario in cases['scenarios']:
        for i,turn in enumerate(scenario['turns']):
            rows.append({'id':f"agent:{scenario['id']}:{i+1}", 'text':turn['prompt']})
    return rows


def source_identity():
    return {'scenarios_sha256':sha(SOURCE), 'labels_sha256':sha(LABELS),
            'rag_questions_sha256':sha(RAG_EVAL_FILE),
            'agent_scenarios_sha256':sha(REPO_ROOT/'data/benchmarks/agent_scenarios.json')}


def validate_source(rows, labels):
    ids=set()
    for row in rows:
        assert row['family_id'] not in ids, 'Duplicate family ID'
        ids.add(row['family_id'])
        assert row['labels'] and set(row['labels']) <= set(labels), 'Unknown or empty labels'
        assert len(set(row['labels'])) == len(row['labels']), 'Repeated label'
        assert 'other' not in row['labels'] or row['labels']==['other'], 'Other is exclusive'
        assert len(row['utterances'])>=2 and all(isinstance(t,str) and t.strip() for t in row['utterances'])
        assert not any(re.search('[\u3400-\u9fff]', t) for t in row['utterances'])


def prepare_plan():
    rows = read_rows(SOURCE)
    label_ids = [l['id'] for l in json.loads(LABELS.read_text())['labels']]
    validate_source(rows, label_ids)
    identity = source_identity()
    if PLAN.exists():
        existing=json.loads(PLAN.read_text())
        if existing['version'] != VERSION or existing['inputs'] != identity:
            raise ValueError('The frozen split inputs changed. Create a new dataset version; do not rewrite held-out data.')
        return existing
    groups = Groups(r['family_id'] for r in rows)
    phrases = [(r['family_id'], t) for r in rows for t in r['utterances']]
    links=[]
    for i,j,score in similar_pairs([p[1] for p in phrases],.80):
        a,b=phrases[i][0],phrases[j][0]
        if a!=b:
            groups.join(a,b);links.append({'a':a,'b':b,'cosine':score})
    components=defaultdict(list)
    for row in rows: components[groups.find(row['family_id'])].append(row)
    # Deterministic grouped multilabel coverage. No model results are used here.
    buckets={name:[] for name in ['train','val','test']}
    remaining=set(components)
    def order(group): return digest([SEED,group])
    for split in ['test','val']:
        counts=Counter()
        target=round(len(rows)*.15)
        while len(buckets[split]) < target:
            def utility(group):
                fams=components[group]
                positives=Counter(label for r in fams for label in r['labels'])
                gain=sum(min(n,max(0,3-counts[label])) for label,n in positives.items())
                return (-gain/max(1,len(fams)),order(group))
            choice=min(remaining,key=utility)
            chosen=components[choice]
            buckets[split].extend(chosen)
            counts.update(label for r in chosen for label in r['labels'])
            remaining.remove(choice)
    for group in sorted(remaining,key=order):buckets['train'].extend(components[group])
    assignment={row['family_id']:{'split':name,'group_id':groups.find(row['family_id'])}
                for name,selected in buckets.items() for row in selected}
    result={'version':VERSION,'seed':SEED,'inputs':identity,'assignment':assignment,
            'pre_split_related_family_links':links,
            'policy':'Whole related groups assigned before generation; no cross-split generation context.'}
    atomic_json(PLAN,result)
    return result


def response_entries(result):
    """Collect all validated JSON containers, including parallel tool calls.

    Compatible providers may emit one Batch call per family. LangChain's default
    first-tool parser then exposes only the first family; do not discard the rest.
    """
    entries=[]
    def collect(value):
        if hasattr(value,'model_dump'):value=value.model_dump()
        if isinstance(value,str):
            try:collect(json.loads(value));return
            except ValueError:pass
            # Recover only complete entry objects from a malformed wrapper;
            # never reconstruct missing customer text or guess a family ID.
            for match in re.finditer(r'\{\s*"family_id"\s*:',value):
                try:
                    item,_=json.JSONDecoder().raw_decode(value[match.start():])
                    collect(item)
                except ValueError:pass
        if isinstance(value,list):
            for item in value:collect(item)
        elif isinstance(value,dict):
            if 'families' in value:collect(value['families'])
            elif 'family_id' in value and 'utterances' in value:
                if isinstance(value['utterances'],str):
                    try:value={**value,'utterances':json.loads(value['utterances'])}
                    except ValueError:return
                entries.append(value)
    collect(result.get('parsed'))
    raw=result['raw']
    for call in raw.tool_calls:collect(call.get('args'))
    for call in raw.invalid_tool_calls:
        try:collect(json.loads(call.get('args','')))
        except (ValueError,TypeError):pass
    if isinstance(raw.content,str):
        content=re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.content.strip())
        try:collect(json.loads(content))
        except ValueError:pass
    return entries


async def generate(limit=None, concurrency=3):
    """Generate each partition in isolated, stateless calls; cache successes only."""
    from pydantic import BaseModel, Field
    from app.core import llm
    from app.eval_transport import evaluation_transport
    plan=prepare_plan()
    labels=json.loads(LABELS.read_text())['labels']
    rows=read_rows(SOURCE)
    data=json.loads(CACHE.read_text()) if CACHE.exists() else {
        'version':VERSION,'plan_sha256':sha(PLAN),'families':{},'usage':[],'failures':{}}
    if data['plan_sha256']!=sha(PLAN):raise ValueError('Generation checkpoint belongs to a different split plan')
    config={'model':llm.resolve_slot('judge')[0], 'temperature':.8, 'thinking':False,
            'method':'function_calling', 'requested_new_utterances':8}
    if data.get('generator_config',config)!=config:
        raise ValueError('Generator settings changed. Use a new version instead of silently mixing generators.')
    if any(v['model']!=config['model'] for v in data['families'].values()):
        raise ValueError('Cached generator model differs from the current writer')
    data['generator_config']=config
    class Entry(BaseModel):
        family_id: str
        utterances: list[str] = Field(description='Exactly 8 new natural English customer messages, each distinct in wording')
    class Batch(BaseModel):
        families: list[Entry]
    pending=[r for r in rows if r['family_id'] not in data['families']]
    if limit is not None:pending=pending[:limit]
    batches=[]
    for split in ['train','val','test']:
        selected=[r for r in pending if plan['assignment'][r['family_id']]['split']==split]
        batches.extend((split,selected[i:i+4]) for i in range(0,len(selected),4))
    semaphore=asyncio.Semaphore(concurrency)
    # Do not include other partitions, RAG questions, or Agent evaluation prompts.
    system=('You write synthetic English user messages for a U.S. pet-supply topic classifier. '
      'For EACH supplied family, write exactly 8 NEW naturally varied messages expressing ONLY the same explicit requests as its two anchors. '
      'Do not change labels, add requests, answer questions, or assert store policies. '
      'Use substantially different wording and syntax, not just greetings or case changes. '
      'Vary length and specificity; include an occasional realistic typo or shorthand, never stereotypes. '
      'Do not change animal/product details to an incompatible product. Messages must stand alone without hidden prior conversation. '
      'Stay within the supplied scenario: these messages share its semantic family and are not independent scenarios. '
      'Do not copy either anchor. Do not prefix labels, scenario IDs, or explanations. '
      'Other means none of the sixteen known topics; do not combine it with a known topic. '
      'This is synthetic draft data, not human gold. Return the requested structured output.')
    async def one(split,batch):
        async with semaphore:
            for attempt in range(2):
                remaining=[r for r in batch if r['family_id'] not in data['families']]
                if not remaining:return
                ids=[r['family_id'] for r in remaining]
                try:
                    with evaluation_transport():
                        writer=llm.get_chat_model(streaming=True,slot='judge',temperature=.8,thinking=False)
                        chain=writer.with_structured_output(Batch,method='function_calling',include_raw=True)
                    result=await asyncio.wait_for(chain.ainvoke([
                        ('system',system),('human',json.dumps({'label_definitions':labels,'families':remaining}))]),180)
                    raw=result['raw']
                    data['usage'].append({'split':split,'families':ids,'attempt':attempt+1,
                        'model':llm.resolve_slot('judge')[0], 'provider_usage':raw.usage_metadata,
                        'recorded_at':datetime.now(timezone.utc).isoformat()})
                    entries=response_entries(result)
                    for entry in entries:
                        family=entry.get('family_id')
                        if family not in ids or family in data['families']:continue
                        texts=entry.get('utterances',[])
                        if not isinstance(texts,list) or not all(isinstance(t,str) for t in texts):continue
                        texts=[t.strip() for t in texts]
                        anchors=next(r['utterances'] for r in remaining if r['family_id']==family)
                        if (len(texts)!=8 or len(set(map(normalized,texts)))!=8
                            or any(normalized(t) in set(map(normalized,anchors)) for t in texts)
                            or any(len(t)<12 or len(t)>650 or re.search('[\u3400-\u9fff]',t) for t in texts)):
                            continue
                        data['families'][family]={'utterances':texts,'model':llm.resolve_slot('judge')[0],
                            'split':split,'source':'llm_synthetic','review_status':'draft_not_human_gold'}
                        data['failures'].pop(family,None)
                    unresolved=[family for family in ids if family not in data['families']]
                    if unresolved:
                        data.setdefault('unparsed',[]).append({'families':unresolved,'split':split,
                            'content':raw.content,'tool_calls':raw.tool_calls,
                            'invalid_tool_calls':raw.invalid_tool_calls,
                            'finish_reason':raw.response_metadata.get('finish_reason')})
                    atomic_json(CACHE,data)
                    print(f"Saved {split}: {len(data['families'])}/{len(rows)} families",flush=True)
                    if unresolved:raise ValueError(f'{len(unresolved)} families still missing valid output')
                    return
                except Exception as exc:
                    for family in ids:
                        if family not in data['families']:data['failures'][family]=type(exc).__name__
                    atomic_json(CACHE,data)
                    detail=str(exc) if type(exc) is ValueError else type(exc).__name__
                    print(f'Generation batch {split} attempt {attempt+1}/2: {detail}',flush=True)
                    if attempt==0:await asyncio.sleep(2)
    await asyncio.gather(*(one(split,batch) for split,batch in batches))
    print(f"Generation checkpoint: {len(data['families'])}/{len(rows)} families saved; {len(data['failures'])} pending failures.")


def load_candidates():
    plan=prepare_plan()
    data=json.loads(CACHE.read_text())
    if data['plan_sha256']!=sha(PLAN):raise ValueError('Generation checkpoint does not match split plan')
    rows=[]
    pending=[]
    for source in read_rows(SOURCE):
        family=source['family_id'];generated=data['families'].get(family)
        if generated is None:pending.append(family);continue
        assignment=plan['assignment'][family]
        for i,text in enumerate(source['utterances']+generated['utterances']):
            rows.append({'id':f'{family}-{i+1:02d}','family_id':family,**assignment,
                'text':text,'labels':source['labels'],'source':'authored_synthetic' if i<2 else 'llm_synthetic',
                'review_status':'draft_not_human_gold'})
    return plan,data,rows,pending


def audit_candidates(rows):
    protected=protected_questions()
    # Compare to protected evals only in the audit; never send their text to writer.
    texts=[r['text'] for r in protected]+[r['text'] for r in rows]
    boundary=len(protected)
    quarantine=set();overlaps=[];cross=[];review=[]
    seen={}
    for i,text in enumerate(texts):
        key=normalized(text)
        if key in seen:
            j=seen[key]
            if i>=boundary:
                row=rows[i-boundary]
                if j<boundary:
                    quarantine.add(row['family_id']);overlaps.append({'family':row['family_id'],'protected_id':protected[j]['id'],'kind':'normalized_exact'})
                elif rows[j-boundary]['family_id']!=row['family_id']:
                    other=rows[j-boundary]
                    if other['split']!=row['split']:
                        quarantine.update([row['family_id'],other['family_id']]);cross.append({'a':other['family_id'],'b':row['family_id'],'kind':'normalized_exact'})
        else:seen[key]=i
    for i,j,score in similar_pairs(texts,.72):
        if j<boundary:continue
        row=rows[j-boundary]
        if i<boundary:
            if score>=.80:
                quarantine.add(row['family_id']);overlaps.append({'family':row['family_id'],'protected_id':protected[i]['id'],'cosine':score})
            continue
        other=rows[i-boundary]
        if row['family_id']==other['family_id'] or row['split']==other['split']:continue
        pair={'a':other['family_id'],'b':row['family_id'],'sample_a':other['id'],'sample_b':row['id'],'cosine':score}
        if score>=.80:
            quarantine.update([row['family_id'],other['family_id']]);cross.append(pair)
        else:review.append(pair)
    # Quarantine every connected planned group, including its related families.
    bad_groups={r['group_id'] for r in rows if r['family_id'] in quarantine}
    quarantine.update(r['family_id'] for r in rows if r['group_id'] in bad_groups)
    return {'quarantined_families':sorted(quarantine),'protected_eval_overlaps':overlaps,
            'cross_split_near_duplicates':cross,
            'lexical_review_candidates':sorted(review,key=lambda p:-p['cosine'])[:200],
            'near_duplicate_threshold':.80,'review_threshold':.72,
            'semantic_audit':'Lexical audit only. No embedding-based guarantee or independent human adjudication.'}


def quality_findings(row):
    """Conservative drift flags, not an automatic labeler or gold adjudicator."""
    text=row['text'].casefold().replace('’',"'")
    labels=set(row['labels']);flags=[]
    if re.search(r'\b(?:family_id|utterances|labels)\s*:',text):flags.append('schema_or_label_artifact')
    # The extra issue must be an actual assertion, not a hypothetical warranty exclusion.
    if 'product_defect' not in labels and re.search(
        r"\b(?:my|the|this|our)\s+(?:[a-z'-]+\s+){0,6}"
        r"(?:arrived (?:broken|damaged)|(?:has |is |was |came |already )?(?:cracked|defective|broken)|stopped working|won't (?:turn on|power on))\b",text):
        if not re.search(r'\b(?:if|would|hypothetical|coverage|warranty|chewing|pet|dog|cat)\b',text):
            flags.append('possible_added_product_defect')
    if 'returns_refunds' not in labels and re.search(
        r"\b(?:i (?:want|need)|i'd like|can i|could i|how do i)\b.{0,25}\b(?:return|exchange|refund)\b",text):
        flags.append('possible_added_return_request')
    if 'receipts_invoices' not in labels and re.search(
        r'\b(?:send|resend|correct|download|provide|copy|itemized)\b.{0,25}\b(?:receipt|invoice)\b',text):
        flags.append('possible_added_receipt_request')
    if 'account_access' not in labels and re.search(
        r"\b(?:can't|cannot|unable to) (?:log in|sign in|access my account)|\bforgot (?:my |the )?password\b",text):
        flags.append('possible_added_login_issue')
    return flags


def semantic_findings():
    path=ROBERTA_DIR/'source/semantic_review.json'
    if not path.exists():
        raise ValueError('Semantic overlap screening is missing. Run scripts.roberta.review_semantics before export.')
    review=json.loads(path.read_text())
    if review['inputs']!=source_identity():raise ValueError('Semantic screening inputs changed')
    findings=[]
    for pair in review.get('candidate_pairs',[]):
        decision=review['decisions'].get(pair['id'],{'decision':'unreviewed','reason':'No valid decision was returned'})
        # Fail closed: uncertain or unavailable comparisons are not quietly passed.
        if decision['decision']!='different':
            findings.append({k:v for k,v in {**pair,**decision}.items() if k not in {'a','b'}})
    return review,findings


def export(output=ROBERTA_DATASET_DIR):
    plan,cache,rows,pending=load_candidates()
    if pending:raise ValueError(f'{len(pending)} families are still missing generation results; continue generation before export')
    audit=audit_candidates(rows)
    bad=set(audit['quarantined_families'])
    semantic,semantic_exclusions=semantic_findings()
    for pair in semantic_exclusions:
        bad.add(pair['a_family'])
        if pair.get('b_family'):bad.add(pair['b_family'])
    bad_groups={r['group_id'] for r in rows if r['family_id'] in bad}
    bad.update(r['family_id'] for r in rows if r['group_id'] in bad_groups)
    audit['quarantined_families']=sorted(bad)
    quality=[{'id':r['id'],'family_id':r['family_id'],'flags':flags}
             for r in rows if (flags:=quality_findings(r))]
    bad_samples={r['id'] for r in quality}
    selected=[r for r in rows if r['family_id'] not in bad and r['id'] not in bad_samples]
    output=Path(output)
    manifest_path=output/'manifest.json'
    provenance={'source_inputs':plan['inputs'],'plan_sha256':sha(PLAN),'generation_sha256':sha(CACHE),
                'builder_sha256':sha(Path(__file__)),
                'semantic_review_sha256':sha(ROBERTA_DIR/'source/semantic_review.json')}
    if manifest_path.exists():
        old=json.loads(manifest_path.read_text())
        if old['version']!=VERSION or old['provenance']!=provenance:
            raise ValueError('Frozen dataset inputs changed. Export a new version to a different directory.')
    output.mkdir(parents=True,exist_ok=True)
    counts={};hashes={};distribution={};family_counts={};prepared={}
    for split in ['train','val','test']:
        samples=sorted((r for r in selected if r['split']==split),key=lambda r:r['id'])
        text=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in samples)
        path=output/f'{split}.jsonl'
        if manifest_path.exists() and (not path.exists() or path.read_text()!=text):
            raise ValueError('Frozen dataset content changed')
        prepared[path]=text
        counts[split]=len(samples);hashes[path.name]=hashlib.sha256(text.encode()).hexdigest()
        distribution[split]=dict(Counter(l for r in samples for l in r['labels']))
        family_counts[split]=len({r['family_id'] for r in samples})
    if not manifest_path.exists():
        for path,text in prepared.items():
            temporary=path.with_suffix('.jsonl.tmp')
            temporary.write_text(text,encoding='utf-8');temporary.replace(path)
    retained_ids={r['id'] for r in selected}
    audit['retained_cross_split_near_duplicates']=[p for p in audit['cross_split_near_duplicates']
        if p.get('sample_a') in retained_ids and p.get('sample_b') in retained_ids]
    # Full construction invariants remain strict even for a draft synthetic release.
    families=defaultdict(set);groups=defaultdict(set);exact=defaultdict(set)
    for row in selected:
        families[row['family_id']].add(row['split']);groups[row['group_id']].add(row['split'])
        exact[normalized(row['text'])].add(row['split'])
    assert all(len(x)==1 for index in [families,groups,exact] for x in index.values())
    assert not audit['retained_cross_split_near_duplicates']
    usage=Counter();usage_by_stage={}
    for stage,records in [('generation',cache['usage']),('semantic_screen',semantic.get('usage',[]))]:
        stage_usage=Counter()
        for record in records:
            for key in ['input_tokens','output_tokens','total_tokens']:
                if record.get('provider_usage',{}):stage_usage[key]+=record['provider_usage'].get(key,0)
        usage_by_stage[stage]=dict(stage_usage);usage.update(stage_usage)
    manifest={'version':VERSION,'language':'en-US','task':'multi_label_topic_classification',
        'status':'synthetic_draft_requires_independent_review','provenance':provenance,
        'counts':counts,'family_counts':family_counts,'label_distribution':distribution,
        'files_sha256':hashes,'provider_usage':dict(usage),'test_frozen':True,
        'token_usage_by_stage':usage_by_stage,
        'usage_scope':'Returned provider usage, including failed-format attempts. Interrupted requests without returned usage may be absent; this is not an invoice.',
        'generator':cache.get('generator_config'),
        'annotation_screen':'Conservative rule flags quarantined; no independent human or second-model gold adjudication.',
        'semantic_screen':{'model':semantic.get('config',{}).get('model'),
                           'candidate_pairs':len(semantic.get('candidate_pairs',[])),
                           'valid_decisions':len(semantic.get('decisions',{})),
                           'policy':'Quarantine same_request, uncertain, and unavailable decisions; candidate screen is not exhaustive.'},
        'policy':'No augmentation after splitting. Generated utterances are confined to their preassigned semantic families. No RAG/Agent evaluation text enters generation.',
        'limitations':['Synthetic authored and model-generated data; not customer traffic or independent human gold.',
            'A shared generator may introduce common style across partitions.',
            'Lexical checks do not rule out every semantic paraphrase; independent review is required before performance claims.',
            'All product, tone, and spelling variants count as dependent members of the same family.']}
    atomic_json(manifest_path,manifest)
    atomic_json(REPORT,{'version':VERSION,'provenance':provenance,'counts':counts,
        'family_counts':family_counts,'label_distribution':distribution,
        'invariants':{'family_disjoint':True,'related_group_disjoint':True,'normalized_text_disjoint':True,
                      'retained_near_duplicates_at_threshold':0,'protected_eval_near_duplicates_at_threshold':0},
        'annotation_quality_quarantine':quality,'semantic_exclusions':semantic_exclusions,**audit})
    print(json.dumps({'counts':counts,'family_counts':family_counts,'quarantined':len(bad),'provider_usage':dict(usage)},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate',action='store_true')
    parser.add_argument('--export',action='store_true')
    parser.add_argument('--audit',action='store_true')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--concurrency',type=int,default=3)
    parser.add_argument('--output',type=Path,default=ROBERTA_DATASET_DIR)
    args=parser.parse_args()
    if args.concurrency<1 or (args.limit is not None and args.limit<1):parser.error('positive limits required')
    if args.generate:asyncio.run(generate(args.limit,args.concurrency))
    elif args.export:export(args.output)
    elif args.audit:
        _,_,rows,pending=load_candidates();print(json.dumps({'pending':pending,**audit_candidates(rows)},indent=2))
    else:
        plan=prepare_plan();print(Counter(x['split'] for x in plan['assignment'].values()))


if __name__=='__main__':main()
