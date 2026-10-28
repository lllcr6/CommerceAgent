"""Read-only validation of an English release. No training, API calls, or writes."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from scripts.roberta import english_dataset as d


def validate(dataset=d.ROBERTA_DATASET_DIR):
    dataset=Path(dataset)
    manifest=json.loads((dataset/'manifest.json').read_text())
    labels={r['id'] for r in json.loads(d.LABELS.read_text())['labels']}
    expected=manifest['provenance']
    assert manifest['language']=='en-US'
    assert expected['source_inputs']==d.source_identity(), 'Source/evaluation inputs changed'
    for name,path in [('plan_sha256',d.PLAN),('generation_sha256',d.CACHE),
                      ('builder_sha256',Path(d.__file__)),
                      ('semantic_review_sha256',d.ROBERTA_DIR/'source/semantic_review.json')]:
        assert d.sha(path)==expected[name], f'Provenance changed: {name}'
    family_splits=defaultdict(set);group_splits=defaultdict(set);text_splits=defaultdict(set)
    ids=set();rows=[];counts={};warnings=[]
    for split in ['train','val','test']:
        path=dataset/f'{split}.jsonl'
        assert d.sha(path)==manifest['files_sha256'][path.name], f'Frozen file changed: {path.name}'
        samples=d.read_rows(path);counts[split]=len(samples)
        assert len(samples)==manifest['counts'][split], f'Count changed: {split}'
        positives=Counter(label for r in samples for label in r['labels'])
        assert set(positives)==labels, f'Missing labels: {split}'
        for label,count in positives.items():
            if split in ['val','test'] and count<30:warnings.append(f'{split}/{label}: {count} positives (<30)')
        for row in samples:
            assert row['id'] not in ids,'Repeated sample ID'
            ids.add(row['id'])
            assert row['split']==split,'Incorrect partition metadata'
            assert row['labels'] and set(row['labels'])<=labels,'Invalid target labels'
            assert len(row['labels'])==len(set(row['labels'])),'Duplicate target labels'
            assert 'other' not in row['labels'] or row['labels']==['other'],'Other is exclusive'
            family_splits[row['family_id']].add(split);group_splits[row['group_id']].add(split)
            text_splits[d.normalized(row['text'])].add(split)
        rows.extend(samples)
    assert all(len(v)==1 for index in [family_splits,group_splits] for v in index.values()), 'Family/group crosses partitions'
    assert all(len(v)==1 for v in text_splits.values()),'Normalized text crosses partitions'
    plan=json.loads(d.PLAN.read_text())['assignment']
    source={r['family_id']:r for r in d.read_rows(d.SOURCE)}
    generated=json.loads(d.CACHE.read_text())['families']
    for row in rows:
        family=row['family_id']
        assert {k:row[k] for k in ['split','group_id']}==plan[family],'Family assignment changed'
        assert row['labels']==source[family]['labels'],'Scenario labels changed'
        assert row['text'] in source[family]['utterances']+generated[family]['utterances'],'Untracked expression'
    audit=d.audit_candidates(rows)
    assert not audit['quarantined_families'],'Retained lexical/evaluation overlap detected'
    _,semantic=d.semantic_findings()
    retained={r['family_id'] for r in rows}
    for pair in semantic:
        assert pair['a_family'] not in retained,'Retained semantic/evaluation overlap'
        assert pair.get('b_family') not in retained,'Retained semantic/group overlap'
    return {'valid':True,'counts':counts,'families':len(family_splits),
            'labels':len(labels),'warnings':warnings,
            'scope':'Mechanical and candidate-screen invariants; not a proof of exhaustive semantic disjointness or human-gold labels.'}


if __name__=='__main__':print(json.dumps(validate(),indent=2))
