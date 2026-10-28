from dataclasses import dataclass

from app.kb import dedup


@dataclass
class Item:
    question: str


def test_normalize_strips_punct_keeps_chinese():
    assert dedup.normalize_question(" 邮费,是多少? ") == "邮费是多少"


def test_dedupe_within_batch_and_against_existing():
    items = [Item("邮费是多少"), Item("邮费是多少?"), Item("怎么退货"), Item("运费怎么算")]
    kept, discarded = dedup.dedupe(items, existing_questions=["运费怎么算"])
    kept_q = [i.question for i in kept]
    assert "邮费是多少" in kept_q
    assert "怎么退货" in kept_q
    assert "运费怎么算" not in kept_q
    assert len(kept) == 2 and len(discarded) == 2
