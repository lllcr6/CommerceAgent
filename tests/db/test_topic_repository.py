from app.db import repository


async def test_insert_and_exclude_classified(db_session_factory):
    qid = await repository.insert_low_confidence(None, "猫窝买大了想退", "retrieval_low_conf", None)
    rid = await repository.insert_review_item("猫窝买大了能不能退货", None)
    await repository.set_matched_review(qid, rid)
    rows = await repository.list_unclassified_questions()
    assert any(r["question_id"] == qid for r in rows)

    n = await repository.insert_topic_classifications(
        [{"question_id": qid, "labels": ["size_fit", "returns_refunds"]}])
    assert n == 1
    rows = await repository.list_unclassified_questions()
    assert not any(r["question_id"] == qid for r in rows)


async def test_unmerged_excluded_from_classify(db_session_factory):

    qid = await repository.insert_low_confidence(None, "猫抓板回收吗", "retrieval_low_conf", None)
    rows = await repository.list_unclassified_questions()
    assert not any(r["question_id"] == qid for r in rows)


async def test_text_prefers_normalized(db_session_factory):
    qid = await repository.insert_low_confidence(None, "这个还能退吗", "retrieval_low_conf", None)
    rid = await repository.insert_review_item("智能猫砂盆能否七天无理由退货", None)
    await repository.set_matched_review(qid, rid)
    rows = await repository.list_pool_texts()
    row = next(r for r in rows if r["question_id"] == qid)
    assert row["text"] == "智能猫砂盆能否七天无理由退货"


async def test_topic_distribution_counts_all_17(db_session_factory):
    qid = await repository.insert_low_confidence(None, "猫窝买大了想退", "retrieval_low_conf", None)
    await repository.insert_topic_classifications(
        [{"question_id": qid, "labels": ["size_fit", "returns_refunds"]}])
    dist = await repository.topic_distribution()
    assert dist["total"] == 1
    assert len(dist["classes"]) == 17
    by_label = {c["label"]: c for c in dist["classes"]}
    assert by_label["size_fit"]["count"] == 1 and by_label["returns_refunds"]["count"] == 1
    assert by_label["delivery_tracking"]["count"] == 0
    assert by_label["size_fit"]["samples"] == ["猫窝买大了想退"]
    assert dist["latest"] is not None
