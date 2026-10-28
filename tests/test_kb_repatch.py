from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from scripts import kb_repatch as repatch


def test_no_changes_result_is_clear_and_english():
    text = repatch.format_result(dict(updated=[], unchanged=69, new=[], preserved=[], pending=0))
    assert 'All 69' in text and 'No changes needed' in text
    assert 'no indexing is needed' in text


def test_unmatched_passages_are_explained_without_guessing_their_origin():
    text = repatch.format_result(dict(updated=[], unchanged=1, new=['New FAQ'], preserved=['ID 2: Old FAQ'], pending=0))
    assert 'kept unchanged' in text and 'never deletes' in text
    assert 'did not import' in text and 'section 1' in text
    assert 'flywheel' not in text


async def test_matches_each_passage_and_preserves_stored_only_rows(tmp_path, monkeypatch):
    (tmp_path / 'policy.md').write_text('Source document')
    stored = [SimpleNamespace(id=i, section_path=path, questions='Question', answer=answer)
              for i, path, answer in [(1, 'Shared', 'Same'), (2, 'Shared', 'Old'), (3, 'Stored only', 'Keep me')]]
    chunks = [SimpleNamespace(section_path=path, questions='Question', answer=answer)
              for path, answer in [('Shared', 'Same'), ('Shared', 'Edited'), ('New', 'New answer')]]
    monkeypatch.setattr(repatch, 'KB_DIR', tmp_path)
    monkeypatch.setattr(repatch, 'SOURCE_TYPES', {'policy.md': 'policy'})
    monkeypatch.setattr(repatch.documents, 'build_chunks', lambda *a, **kw: chunks)
    monkeypatch.setattr(repatch.repository, 'list_chunks_by_content_types', AsyncMock(return_value=stored))
    writer = AsyncMock()
    monkeypatch.setattr(repatch.repository, 'repend_chunk_text', writer)
    monkeypatch.setattr(repatch.repository, 'count_chunks_by_status', AsyncMock(return_value=1))
    result = await repatch.apply_edits()
    writer.assert_awaited_once_with(2, 'Question', 'Edited')
    assert result['unchanged'] == 1 and result['preserved'] == ['ID 3: Stored only']
    assert len(result['new']) == 1 and result['pending'] == 1
    assert 'section 4' in repatch.format_result(result)
