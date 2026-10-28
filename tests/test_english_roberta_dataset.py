import json
from pathlib import Path

import pytest

from scripts.roberta import english_dataset as data


def test_authored_schema_is_english_and_other_is_exclusive():
    labels=[r['id'] for r in json.loads(data.LABELS.read_text())['labels']]
    source=data.read_rows(data.SOURCE)
    data.validate_source(source,labels)
    assert len(labels)==17
    assert len(source)==400
    assert len({r['family_id'] for r in source})==400
    assert any(len(r['labels'])>1 for r in source)


def test_plan_groups_sources_before_generation_and_is_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(data,'PLAN',tmp_path/'split_plan.json')
    plan=data.prepare_plan()
    assert {v['split'] for v in plan['assignment'].values()}=={'train','val','test'}
    groups={}
    for assigned in plan['assignment'].values():
        groups.setdefault(assigned['group_id'],set()).add(assigned['split'])
    assert all(len(splits)==1 for splits in groups.values())
    before=data.PLAN.read_bytes()
    assert data.prepare_plan()==plan
    assert data.PLAN.read_bytes()==before
    monkeypatch.setattr(data,'source_identity',lambda:{'changed':'input'})
    with pytest.raises(ValueError,match='frozen split inputs changed'):data.prepare_plan()


def test_cross_split_paraphrase_and_eval_copy_quarantine_entire_related_groups(monkeypatch):
    monkeypatch.setattr(data,'protected_questions',lambda:[{'id':'rag:heldout','text':'The gate latch will not close securely.'}])
    rows=[
      {'id':'a1','family_id':'a','group_id':'linked','split':'train','text':'How can I request a duplicate itemized receipt for my company?'},
      {'id':'b1','family_id':'b','group_id':'b','split':'test','text':'How can I request a duplicate itemized invoice for my company?'},
      {'id':'c1','family_id':'c','group_id':'linked','split':'train','text':'This message is a distant member of the same known source conversation.'},
      {'id':'d1','family_id':'d','group_id':'d','split':'val','text':'The gate latch will not close securely!'}]
    audit=data.audit_candidates(rows)
    assert set(audit['quarantined_families'])=={'a','b','c','d'}
    assert audit['protected_eval_overlaps']
    assert audit['cross_split_near_duplicates']


def test_missing_generation_cannot_be_exported(tmp_path, monkeypatch):
    monkeypatch.setattr(data,'load_candidates',lambda:({}, {}, [], ['missing-family']))
    with pytest.raises(ValueError,match='continue generation before export'):data.export(tmp_path)
    assert list(tmp_path.iterdir())==[]


def test_normalization_handles_case_punctuation_numbers_and_contractions():
    assert data.normalized("I can't access order 12345!")==data.normalized('I cannot access order 98765.')
    assert data.words('A parcel and an invoice')==data.words('A package and a receipt')


def test_frozen_export_refuses_modified_test_data(tmp_path, monkeypatch):
    monkeypatch.setattr(data,'PLAN',tmp_path/'plan.json')
    monkeypatch.setattr(data,'CACHE',tmp_path/'cache.json')
    monkeypatch.setattr(data,'REPORT',tmp_path/'audit.json')
    monkeypatch.setattr(data,'ROBERTA_DIR',tmp_path)
    (tmp_path/'source').mkdir()
    (tmp_path/'source/semantic_review.json').write_text('{}')
    monkeypatch.setattr(data,'semantic_findings',lambda:({},[]))
    data.PLAN.write_text('{}');data.CACHE.write_text('{}')
    rows=[{'id':'train-a','family_id':'a','group_id':'a','split':'train',
           'text':'The water pump produces a rattling noise.', 'labels':['product_defect']},
          {'id':'test-b','family_id':'b','group_id':'b','split':'test',
           'text':'Please send an itemized purchase document to accounting.', 'labels':['receipts_invoices']}]
    monkeypatch.setattr(data,'load_candidates',lambda:({'inputs':{}},{'usage':[]},rows,[]))
    monkeypatch.setattr(data,'protected_questions',lambda:[])
    output=tmp_path/'dataset'
    data.export(output)
    path=output/'test.jsonl'
    original=path.read_bytes()
    data.export(output)
    assert path.read_bytes()==original
    path.write_text('tampered test')
    with pytest.raises(ValueError,match='Frozen dataset content changed'):data.export(output)


def test_parallel_family_tool_calls_are_all_kept_without_retry():
    from langchain_core.messages import AIMessage
    first={'family_id':'a','utterances':['first']}
    second={'family_id':'b','utterances':['second']}
    raw=AIMessage(content='',tool_calls=[
        {'name':'Batch','id':'1','args':{'families':[first]}},
        {'name':'Batch','id':'2','args':{'families':[second]}}])
    collected=data.response_entries({'parsed':{'families':[first]},'raw':raw})
    assert {r['family_id'] for r in collected}=={'a','b'}


def test_json_content_uses_same_family_validation_shape():
    from langchain_core.messages import AIMessage
    raw=AIMessage(content='```json\n{"families":[{"family_id":"a","utterances":["example"]}]}\n```')
    assert data.response_entries({'parsed':None,'raw':raw})==[{'family_id':'a','utterances':['example']}]


def test_published_release_has_all_labels_and_no_overlap():
    from scripts.roberta.validate_dataset import validate
    release=validate()
    assert release['valid']
    assert release['labels']==17
    assert not any(w.startswith('test/') for w in release['warnings'])


def test_release_validator_rejects_cross_split_family_even_if_hash_is_updated(tmp_path):
    import shutil
    from scripts.roberta.validate_dataset import validate
    dataset=tmp_path/'dataset'
    shutil.copytree(data.ROBERTA_DATASET_DIR,dataset)
    sample=data.read_rows(dataset/'train.jsonl')[0]
    copied={**sample,'split':'test','id':sample['id']+'-copy'}
    with (dataset/'test.jsonl').open('a') as stream:stream.write(json.dumps(copied)+'\n')
    manifest=json.loads((dataset/'manifest.json').read_text())
    manifest['counts']['test']+=1
    manifest['files_sha256']['test.jsonl']=data.sha(dataset/'test.jsonl')
    (dataset/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(AssertionError,match='Family/group crosses partitions'):validate(dataset)


async def test_english_release_cannot_run_retired_chinese_golden(monkeypatch,capsys):
    from unittest.mock import AsyncMock
    from scripts.roberta import validate_golden
    provider=AsyncMock(side_effect=AssertionError('No Chinese golden/model requests'))
    monkeypatch.setattr(validate_golden,'prelabel_batch',provider)
    assert await validate_golden.main()==1
    provider.assert_not_called()
    assert 'No independently reviewed English gold set' in capsys.readouterr().out


async def test_complete_generation_reuses_cache_without_model_requests(monkeypatch):
    from unittest.mock import Mock
    from app.core import llm
    original=data.CACHE.read_bytes()
    model=json.loads(original)['generator_config']['model']
    monkeypatch.setattr(llm,'resolve_slot',lambda _: (model,'',''))
    provider=Mock(side_effect=AssertionError('Completed families must not call the model'))
    monkeypatch.setattr(llm,'get_chat_model',provider)
    await data.generate()
    provider.assert_not_called()
    assert data.CACHE.read_bytes()==original
