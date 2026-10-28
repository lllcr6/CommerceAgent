from scripts.judge_check import (evidence_from_citations, expected_faithful,
                                 gradable, verdict_row)

CITS = [{"n": 1, "question": "退款时效", "answer": "到账时效以平台售后规则为准。"},
        {"n": 2, "question": "处理时限", "answer": "退款 3 个工作日。"}]


class _Row:
    def __init__(self, eval_id, status, citations):
        self.eval_id, self.status, self.citations = eval_id, status, citations


def test_reconstructs_original_numbered_evidence():

    assert evidence_from_citations(CITS) == (
        "[1] 退款时效:到账时效以平台售后规则为准。\n[2] 处理时限:退款 3 个工作日。")


def test_historical_snapshot_infers_citation_numbers():
    assert evidence_from_citations([{"question": "运费", "answer": "买家承担。"}]) == "[1] 运费:买家承担。"
    assert evidence_from_citations(None) == ""


def test_review_state_maps_to_expected_faithfulness():
    assert expected_faithful("resolved") is False
    assert expected_faithful("dismissed") is True
    assert expected_faithful("unresolved") is None


def test_gradable_case_requires_review_and_snapshot():
    rows = [_Row("A50", "dismissed", CITS),
            _Row("E15", "resolved", CITS),
            _Row("E17", "unresolved", CITS),
            _Row("A43", "resolved", None)]
    assert [r.eval_id for r in gradable(rows)] == ["A50", "E15"]


def test_judge_agreement_and_disagreement():
    assert verdict_row("E15", "resolved", False)["agree"] is True
    assert verdict_row("E15", "resolved", True)["agree"] is False
    assert verdict_row("A50", "dismissed", False)["agree"] is False

    row = verdict_row("A50", "dismissed", None)
    assert row["agree"] is False and row["actual"] is None
