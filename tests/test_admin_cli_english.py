import ast
from pathlib import Path
import re
from unittest.mock import AsyncMock

import pytest
from scripts import eval_rag


@pytest.mark.parametrize('filename', sorted(
    str(path) for folder in ('app', 'scripts', 'mcp_servers')
    for path in Path(folder).rglob('*.py')
))
def test_admin_cli_message_templates_are_english(filename):
    """Check emitted templates, excluding comments, raw data, and persisted enum keys."""
    tree = ast.parse(Path(filename).read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ''
        if name not in {'print', '_log', 'warning', 'error', 'info', 'exception', 'RuntimeError', 'ValueError'}:
            continue
        for arg in node.args:
            # FormattedValue children can contain wire-format keys or user data.
            fragments = [arg.value] if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else []
            if isinstance(arg, ast.JoinedStr):
                fragments += [part.value for part in arg.values if isinstance(part, ast.Constant) and isinstance(part.value, str)]
            assert not any(re.search(r'[\u3400-\u9fff]', text) for text in fragments), f'{filename}:{node.lineno}'


@pytest.mark.parametrize('skip', [True, False])
async def test_evaluation_main_emits_english_and_preserves_results(tmp_path, monkeypatch, capsys, skip):
    sample = dict(id='policy-1', bucket='A_policy', query='How much is shipping?', expect_points=['$49'], relevant_chunk_ids=[53])
    monkeypatch.setattr(eval_rag, '_load', lambda: [sample])
    monkeypatch.setattr(eval_rag, 'check_live_annotations', AsyncMock())
    monkeypatch.setattr(eval_rag, '_retrieve', AsyncMock(return_value=[{'id': 53, 'answer': 'Free shipping at $49.'}]))
    monkeypatch.setattr(eval_rag, '_generation', AsyncMock(side_effect=RuntimeError('Model provider unavailable')))
    monkeypatch.setattr(eval_rag, '_kb_chunks', AsyncMock(return_value=69))
    monkeypatch.setattr(eval_rag, '_read_notes', AsyncMock(return_value={}))
    monkeypatch.setattr(eval_rag.llm, 'resolve_slot', lambda _: ('test-judge', '', ''))
    monkeypatch.setattr(eval_rag, '_LINES', [])
    monkeypatch.setattr(eval_rag, '_errs', [])
    monkeypatch.setattr(eval_rag, 'SKIP_GEN', skip)
    monkeypatch.setattr(eval_rag, '_ROOT', tmp_path)
    monkeypatch.setattr(eval_rag, '_OUT_DIR', tmp_path)
    monkeypatch.setattr(eval_rag, '_OUT_JSON', tmp_path / 'result.json')
    monkeypatch.setattr(eval_rag, '_OUT_TXT', tmp_path / 'result.txt')
    await eval_rag.main()
    output = capsys.readouterr().out
    assert not re.search(r'[\u3400-\u9fff]', output)
    assert 'Stage 1' in output and 'Stage 2' in output
    assert 'Generation skipped' in output if skip else 'Generation incomplete' in output
    import json
    result = json.loads((tmp_path / 'result.json').read_text())
    assert result['retrieval']['vector']['overall']['recall'] == 1.0
    assert result['retrieval']['vector']['overall']['precision'] == 0.2
    assert result['generation'] is None


async def test_generation_diagnostics_are_english_including_missing_and_flagged_results(monkeypatch, capsys):
    samples = [dict(id='policy-1', bucket='A_policy', query='Shipping fee?', expect_points=['$49']),
               dict(id='absent-1', bucket='D_absent', query='Can you prescribe medicine?')]
    async def generated(strategy, sample, *args):
        flagged = strategy == 'hybrid_rerank'
        return dict(strat=strategy, bucket=sample['bucket'], coverage=None if strategy == 'bm25' else 0.5,
                    faithful=False if flagged else None,
                    faith_detail=dict(id='policy-1', query=sample['query'], bucket=sample['bucket'], answer='Unsupported answer', reason='Not in evidence') if flagged else None,
                    guard_hits=[dict(id='policy-1', strat=strategy, models=['MH-FAKE'], fixed=False)] if flagged else [])
    monkeypatch.setattr(eval_rag, '_gen_one', generated)
    monkeypatch.setattr(eval_rag, '_refusal_one', AsyncMock(return_value=dict(refused=False, detail=dict(id='absent-1', query='Can you prescribe medicine?', section_path='Policy'))))
    monkeypatch.setattr(eval_rag, 'get_chat_model', lambda: object())
    monkeypatch.setattr(eval_rag.llm, 'structured', lambda *a, **k: object())
    monkeypatch.setattr(eval_rag.llm, 'resolve_slot', lambda _: ('test-judge', '', ''))
    monkeypatch.setattr(eval_rag, '_ledger', AsyncMock())
    monkeypatch.setattr(eval_rag, '_errs', [])
    result = await eval_rag._generation(samples, {})
    output = capsys.readouterr().out
    assert not re.search(r'[\u3400-\u9fff]', output)
    assert 'N/A' in output and 'Unsupported model numbers: MH-FAKE' in output
    assert 'Cases flagged as unfaithful: 1' in output
    assert result['refusal']['rate'] == 0
    assert result['answer_coverage']['bm25']['overall'] is None
    assert result['answer_coverage']['vector']['overall'] == 0.5


async def test_review_queue_output_does_not_expose_legacy_enum_labels(monkeypatch, capsys):
    from app.db import repository
    monkeypatch.setattr(repository, 'upsert_faith_case', AsyncMock(return_value=(1, True)))
    monkeypatch.setattr(repository, 'list_faith_cases', AsyncMock(return_value=([], 9, {'unresolved': 3, 'resolved': 4, 'dismissed': 2})))
    monkeypatch.setattr(eval_rag.llm, 'resolve_slot', lambda _: ('test-judge', '', ''))
    case = dict(id='policy-1', bucket='A_policy', query='Shipping fee?', answer='Answer', reason='Reason', citations=[])
    await eval_rag._ledger([case])
    output = capsys.readouterr().out
    assert not re.search(r'[\u3400-\u9fff]', output)
    assert 'unresolved 3' in output and 'resolved 4' in output
    assert '1 previously reviewed cases reopened' in output
