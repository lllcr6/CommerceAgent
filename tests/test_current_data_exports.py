import json
from unittest.mock import Mock

from scripts import cost_by_intent, eval_flywheel, prepare_english_rag


def test_local_usage_export_contains_separate_tokens_and_no_model_call(tmp_path, monkeypatch):
    report={'meta':{'source':'Local backend usage','days':7},'total_tokens':1200,'total_requests':2,
            'rows':[{'intent':'product_question','count':2,'input_tokens':1000,'output_tokens':200,'avg_tokens':600,'share':1}]}
    reader=Mock(return_value=report)
    monkeypatch.setattr(cost_by_intent,'intent_report',reader)
    monkeypatch.setattr(cost_by_intent.sys,'argv',['cost-report'])
    monkeypatch.setattr(cost_by_intent,'_OUT_DIR',tmp_path)
    monkeypatch.setattr(cost_by_intent,'_OUT',tmp_path/'cost_by_intent.txt')
    monkeypatch.setattr(cost_by_intent,'_OUT_JSON',tmp_path/'cost_by_intent.json')
    assert cost_by_intent.main()==0
    saved=json.loads((tmp_path/'cost_by_intent.json').read_text())
    assert saved['rows'][0]['input_tokens']==1000
    assert saved['rows'][0]['output_tokens']==200
    assert saved['meta']['source']=='Local backend usage'
    text=(tmp_path/'cost_by_intent.txt').read_text()
    assert 'Input tokens' in text and 'Output tokens' in text and 'Langfuse' not in text
    reader.assert_called_once_with(7)


async def test_history_cli_only_reads_completed_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(eval_flywheel,'RAG_REPORTS_DIR',tmp_path)
    monkeypatch.setattr(eval_flywheel.sys,'argv',['eval-flywheel'])
    assert await eval_flywheel.main()==0
    assert 'No fully completed' in capsys.readouterr().out
    assert list(tmp_path.iterdir())==[]


def test_english_preparation_does_not_create_legacy_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_english_rag,'ROOT',tmp_path)
    monkeypatch.setattr(prepare_english_rag,'RAG_EVAL_FILE',tmp_path/'questions.jsonl')
    (tmp_path/'questions.jsonl').write_text('old input')
    prepare_english_rag.write([],[],False)
    assert not (tmp_path/'legacy-zh').exists()
    assert (tmp_path/'questions.jsonl').read_text()==''
    assert json.loads((tmp_path/'chunks.json').read_text())['language']=='en-US'
