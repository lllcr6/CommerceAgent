"""Screen likely family/evaluation overlaps; this is not classifier evaluation.

Uses a separate configured model from the writer. Cached decisions are reused.
Only source anchors and protected evaluation questions enter this audit; findings
are never used as generation prompts or classifier training features.
"""
import asyncio
import argparse
from collections import defaultdict
import json
import re

from scripts.roberta import english_dataset as d

PATH=d.ROBERTA_DIR/'source/semantic_review.json'


def candidate_pairs():
    source=d.read_rows(d.SOURCE);plan=d.prepare_plan()
    protected=d.protected_questions()
    entries=[{'family':s['family_id'],'text':text,'labels':s['labels'],
              'split':plan['assignment'][s['family_id']]['split']} for s in source for text in s['utterances']]
    entries += [{'protected':p['id'],'text':p['text']} for p in protected]
    by_family={};by_protected={}
    for i,j,score in d.similar_pairs([e['text'] for e in entries],.20):
        a,b=entries[i],entries[j]
        if 'protected' in a:continue
        if 'protected' in b:
            key=(a['family'],b['protected'])
            item={'a_family':a['family'],'protected_id':b['protected'],
                  'a':a['text'],'b':b['text'],'cosine':score,'kind':'protected_eval'}
            if key not in by_protected or score>by_protected[key]['cosine']:by_protected[key]=item
        elif a['family']!=b['family'] and a['split']!=b['split']:
            key=tuple(sorted((a['family'],b['family'])))
            item={'a_family':a['family'],'b_family':b['family'],
                  'a':a['text'],'b':b['text'],'cosine':score,'kind':'cross_split_family'}
            if key not in by_family or score>by_family[key]['cosine']:by_family[key]=item
    selected={}
    # Up to two closest families per protected question, and three cross-split
    # neighbors per source family. Similarity is only candidate retrieval.
    for collection,field,limit in [(by_protected.values(),'protected_id',2),(by_family.values(),'a_family',3)]:
        counts=defaultdict(int)
        for item in sorted(collection,key=lambda p:-p['cosine']):
            key=item[field]
            if counts[key]>=limit:continue
            counts[key]+=1
            ident=d.digest([item['kind'],item['a_family'],item.get('b_family'),item.get('protected_id')])[:20]
            selected[ident]={'id':ident,**item}
    return list(selected.values())


async def main(batch_size=16):
    from app.core.llm import get_chat_model,resolve_slot
    from app.eval_transport import evaluation_transport
    pairs=candidate_pairs();identity=d.source_identity()
    config={'model':resolve_slot('chat')[0],'temperature':0,'thinking':False,'candidate_policy':'lexical-0.20-top2-protected-top3-cross-family-v1'}
    saved=json.loads(PATH.read_text()) if PATH.exists() else {'inputs':identity,'config':config,'decisions':{},'usage':[]}
    if saved['inputs']!=identity or saved['config']!=config:raise ValueError('Semantic audit inputs changed; use a new version')
    pending=[p for p in pairs if p['id'] not in saved['decisions']]
    sem=asyncio.Semaphore(3)
    system=('You screen possible dataset leakage, not classifier accuracy. Compare customer requests A and B. '
        'Return JSON only: {"items":[{"id":"provided ID","decision":"same_request|different|uncertain","reason":"brief English reason"}]}. '
        'same_request means a paraphrase, or a simple product/animal/color substitution with the same requested action and materially same constraints. '
        'Merely sharing a broad topic is NOT enough. Different failure causes, conditions, requests, policy facets, or an added second request are different. '
        'For example, a missing delivery and delivery signature rules differ. A receipt under another name and a receipt in another format differ. '
        'Asking whether spare lids are in stock versus whether spare trays are in stock IS a product substitution. '
        'Do not confuse opposite or negated requests. Use uncertain if you cannot confidently establish equivalence or difference. '
        'Do not answer either question or make store-policy claims. Evaluate each pair independently.')
    async def batch(items):
        async with sem:
            for attempt in range(2):
                todo=[p for p in items if p['id'] not in saved['decisions']]
                if not todo:return
                try:
                    with evaluation_transport():
                        model=get_chat_model(streaming=True,temperature=0,thinking=False)
                    raw=await asyncio.wait_for(model.bind(response_format={'type':'json_object'}).ainvoke([
                        ('system',system),('human',json.dumps({'pairs':[{'id':p['id'],'A':p['a'],'B':p['b']} for p in todo]}))]),180)
                    saved['usage'].append({'ids':[p['id'] for p in todo],'provider_usage':raw.usage_metadata})
                    text=re.sub(r'^```(?:json)?\s*|\s*```$', '',raw.content.strip())
                    result=json.loads(text)
                    records=result.get('items',[])
                    if isinstance(records,str):records=json.loads(records)
                    wanted={p['id'] for p in todo}
                    for decision in records:
                        if decision.get('id') in wanted and decision.get('decision') in {'same_request','different','uncertain'}:
                            saved['decisions'][decision['id']]=decision
                    d.atomic_json(PATH,saved)
                    print('Semantic comparisons saved:',len(saved['decisions']),'/',len(pairs),flush=True)
                except Exception as exc:
                    print('Semantic batch:',type(exc).__name__,flush=True)
                if attempt==0 and any(p['id'] not in saved['decisions'] for p in items):await asyncio.sleep(2)
    await asyncio.gather(*(batch(pending[i:i+batch_size]) for i in range(0,len(pending),batch_size)))
    saved['candidate_pairs']=pairs
    saved['complete']=all(p['id'] in saved['decisions'] for p in pairs)
    d.atomic_json(PATH,saved)
    print('Semantic screen complete:',saved['complete'],'pairs:',len(pairs))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-size',type=int,default=16)
    args=parser.parse_args()
    if args.batch_size<1:parser.error('positive batch size required')
    asyncio.run(main(args.batch_size))
