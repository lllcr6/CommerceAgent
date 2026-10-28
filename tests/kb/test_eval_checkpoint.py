from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from app.kb.eval_checkpoint import Checkpoint
from scripts import eval_rag


def test_resume_requires_exact_signature_and_rerun_starts_empty(tmp_path):
    with pytest.raises(ValueError, match='No resumable'):
        Checkpoint(tmp_path, 'a', resume=True)
    first = Checkpoint(tmp_path, 'a')
    first.put(['answer', '1'], {'value': 'saved'})
    continued = Checkpoint(tmp_path, 'a', resume=True)
    assert continued.get(['answer', '1']) == {'value': 'saved'}
    with pytest.raises(ValueError, match='configuration has changed'):
        Checkpoint(tmp_path, 'changed-model', resume=True)
    fresh = Checkpoint(tmp_path, 'a')
    assert fresh.get(['answer', '1']) is None
    assert first.directory.exists()
    assert not list(tmp_path.rglob('*.tmp'))


@pytest.mark.parametrize('value', [AIMessage(content='Saved answer'), eval_rag._Cov(covered_count=0),
                                     eval_rag._Faith(faithful=False, reason='Unsupported'),
                                     {'sufficient': False}, []])
async def test_successful_calls_survive_new_checkpoint_instance(tmp_path, monkeypatch, value):
    monkeypatch.setattr(eval_rag, '_checkpoint', Checkpoint(tmp_path, 'a'))
    first = AsyncMock(return_value=value)
    assert await eval_rag._try(first, 'task') == value
    monkeypatch.setattr(eval_rag, '_checkpoint', Checkpoint(tmp_path, 'a', resume=True))
    again = AsyncMock(side_effect=AssertionError('Must not call provider'))
    assert await eval_rag._try(again, 'task') == value
    again.assert_not_called()


async def test_failed_calls_retry_and_changed_answer_invalidates_judge_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_rag, '_checkpoint', Checkpoint(tmp_path, 'a'))
    monkeypatch.setattr(eval_rag.asyncio, 'sleep', AsyncMock())
    monkeypatch.setattr(eval_rag, '_errs', [])
    failing = AsyncMock(side_effect=TimeoutError())
    assert await eval_rag._try(failing, 'cov:1', 'old answer') is None
    assert failing.await_count == 2
    success = AsyncMock(return_value=eval_rag._Cov(covered_count=1))
    assert await eval_rag._try(success, 'cov:1', 'old answer') == eval_rag._Cov(covered_count=1)
    changed = AsyncMock(return_value=eval_rag._Cov(covered_count=0))
    assert await eval_rag._try(changed, 'cov:1', 'repaired answer') == eval_rag._Cov(covered_count=0)
    changed.assert_awaited_once()


async def test_retrieval_results_reused_without_embedding_or_reranking(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_rag, '_checkpoint', Checkpoint(tmp_path, 'a'))
    provider = AsyncMock(return_value=[{'id': 53, 'answer': 'Shipping policy', 'score': 0.9}])
    monkeypatch.setattr(eval_rag.retrieval, 'search_knowledge', provider)
    sample = {'id': '1', 'query': 'Shipping?'}
    hits = await eval_rag._retrieve('hybrid', sample)
    monkeypatch.setattr(eval_rag, '_checkpoint', Checkpoint(tmp_path, 'a', resume=True))
    assert await eval_rag._retrieve('hybrid', sample) == hits
    provider.assert_awaited_once()


def test_signature_changes_for_model_dataset_and_live_knowledge(monkeypatch):
    base = eval_rag._signature([])
    monkeypatch.setattr(eval_rag.settings, 'judge_model', 'another-judge')
    assert eval_rag._signature([]) != base
    changed_model = eval_rag._signature([])
    assert eval_rag._signature([{'id': 999, 'answer': 'A new passage'}]) != changed_model


async def test_cancellation_keeps_completed_calls_only(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setattr(eval_rag, '_checkpoint', Checkpoint(tmp_path, 'a'))
    done = AsyncMock(return_value={'answer': 'Ready'})
    await eval_rag._try(done, 'done')
    cancelled = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await eval_rag._try(cancelled, 'unfinished')
    resumed = Checkpoint(tmp_path, 'a', resume=True)
    assert resumed.get(['done', None]) is not None
    assert resumed.get(['unfinished', None]) is None


async def test_checkpoint_disk_failure_does_not_repeat_paid_call(tmp_path, monkeypatch):
    checkpoint = Checkpoint(tmp_path, 'a')
    monkeypatch.setattr(eval_rag, '_checkpoint', checkpoint)
    def fail(*args):
        raise OSError('Disk full')
    monkeypatch.setattr(checkpoint, 'put', fail)
    provider = AsyncMock(return_value=AIMessage(content='Already generated'))
    with pytest.raises(OSError, match='Disk full'):
        await eval_rag._try(provider, 'answer')
    provider.assert_awaited_once()


def test_continue_rejects_legacy_without_creating_or_migrating(tmp_path):
    from app.kb.eval_checkpoint import atomic_json
    root=tmp_path/'checkpoints'
    atomic_json(root/'current.json',{'run_id':'old','signature':'same'})
    before=set(tmp_path.rglob('*'))
    with pytest.raises(ValueError, match='Unsupported checkpoint layout'):
        Checkpoint(root,'same',resume=True)
    assert set(tmp_path.rglob('*')) == before


@pytest.mark.parametrize('missing', ['run', 'checkpoints'])
def test_continue_missing_storage_fails_without_new_files(tmp_path, missing):
    import shutil
    root=tmp_path/'checkpoints'
    first=Checkpoint(root,'same')
    first.put('done',{'value':'keep'})
    pointer=(root/'current.json').read_bytes()
    shutil.rmtree(first.directory.parent if missing == 'run' else first.directory)
    before=set(tmp_path.rglob('*'))
    with pytest.raises(ValueError, match='checkpoints are missing'):
        Checkpoint(root,'same',resume=True)
    assert set(tmp_path.rglob('*')) == before
    assert (root/'current.json').read_bytes() == pointer


@pytest.mark.parametrize('failure', ['prepare', 'pointer'])
def test_rerun_failure_keeps_previous_selected_and_removes_incomplete_run(tmp_path, monkeypatch, failure):
    from app.kb import eval_checkpoint as module
    root=tmp_path/'checkpoints'
    first=Checkpoint(root,'same')
    first.put('done', {'value':'keep'})
    pointer=(root/'current.json').read_bytes()
    before=set(tmp_path.rglob('*'))
    def prepare(run, checkpoint):
        (run/'questions.jsonl').write_text('prepared')
        if failure == 'prepare': raise OSError('Preparation failed')
    original=module.atomic_json
    def write(path,value):
        if Path(path) == root/'current.json': raise OSError('Pointer failed')
        return original(path,value)
    from pathlib import Path
    if failure == 'pointer': monkeypatch.setattr(module,'atomic_json',write)
    with pytest.raises(OSError): Checkpoint(root,'same',prepare=prepare)
    assert (root/'current.json').read_bytes() == pointer
    assert set(tmp_path.rglob('*')) == before
    assert Checkpoint(root,'same',resume=True).get('done') == {'value':'keep'}


def test_continue_does_not_prepare_or_change_pointer(tmp_path):
    from unittest.mock import Mock
    root=tmp_path/'checkpoints'
    first=Checkpoint(root,'same')
    before=set(tmp_path.rglob('*'))
    pointer=(root/'current.json').read_bytes()
    prepare=Mock(side_effect=AssertionError('must not prepare on Continue'))
    again=Checkpoint(root,'same',resume=True,prepare=prepare)
    assert again.directory == first.directory
    assert set(tmp_path.rglob('*')) == before
    assert (root/'current.json').read_bytes() == pointer
    prepare.assert_not_called()


def test_signature_ignores_observability_configuration_but_keeps_scoring_parameters(monkeypatch):
    base=eval_rag._signature([])
    monkeypatch.setattr(eval_rag.settings,'langfuse_base_url','http://another-local-telemetry-host')
    assert eval_rag._signature([])==base
    monkeypatch.setattr(eval_rag.settings,'evidence_confidence_threshold',0.123)
    assert eval_rag._signature([])!=base


def test_admin_job_source_is_not_a_scoring_input(monkeypatch):
    from pathlib import Path
    base=eval_rag._signature([])
    original=Path.read_text
    def changed(path,*args,**kwargs):
        if str(path).endswith('/app/core/jobs.py'):
            return 'admin UI job registry changed'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',changed)
    assert eval_rag._signature([])==base
