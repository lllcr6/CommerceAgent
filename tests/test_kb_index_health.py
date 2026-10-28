from app.api.kb import index_health


def test_clean_english_index_reports_matching_counts():
    result = index_health({'total': 69}, {'online': True, 'count': 69, 'collection': 'knowledge_en_v1'}, None, True)
    assert result['label'] == 'Counts match'
    assert result['level'] == 'pass'
    assert 'historical' not in result['detail']
    assert 'do not verify individual' in result['detail']


def test_index_outage_is_distinct_from_database_outage():
    assert index_health({}, {'online': False}, None, None)['label'] == 'Index offline'
    result = index_health({}, {'online': True}, 'Connection refused', None)
    assert result['label'] == 'Index online'
    assert 'unverified' in result['detail']


def test_same_scope_counts_match_or_need_sync():
    assert index_health({}, {'online': True}, None, True)['label'] == 'Counts match'
    assert index_health({}, {'online': True}, None, False)['label'] == 'Sync needed'
