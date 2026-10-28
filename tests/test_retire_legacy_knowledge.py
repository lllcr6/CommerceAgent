import pytest
from scripts.retire_legacy_knowledge import split_corpus


def row(cid, question='Shipping', answer='Shipping is free at $49.'):
    return dict(id=cid, question=question, answer=answer, section_path='Policy / Shipping', content_type='policy', category='Policy')


def test_only_verified_english_content_is_kept_and_chinese_is_retired():
    english, legacy = split_corpus([row(53), row(1, '运费', '满99包邮')], [row(1)])
    assert [r['id'] for r in english] == [53]
    assert [r['id'] for r in legacy] == [1]


@pytest.mark.parametrize('rows', [[], [row(53), row(54)], [row(53, answer='Different policy')]])
def test_missing_duplicate_or_changed_english_blocks_cleanup(rows):
    with pytest.raises(ValueError):
        split_corpus(rows, [row(1)])


def test_unrecognized_english_knowledge_is_not_silently_deleted():
    with pytest.raises(ValueError, match='Unrecognized'):
        split_corpus([row(53), row(54, 'Reviewed FAQ', 'A new answer')], [row(1)])
