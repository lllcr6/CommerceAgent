import pytest

from app.kb import dualwrite, mining


class _FakeRepo:


    def __init__(self, pairs):
        self.rows = []
        self.pairs = pairs
        self.status = {}

    async def insert_staging(self, batch_no, source_ref, question, answer):
        rid = len(self.rows) + 1
        self.rows.append({"id": rid, "batch_no": batch_no, "question": question,
                          "answer": answer})
        self.status[rid] = "extracted"
        return rid

    async def list_staging_by_status(self, status):
        out = []
        for r in self.rows:
            if self.status[r["id"]] == status:
                out.append(type("Row", (), {**r, "batch_no": r["batch_no"],
                                            "question": r["question"],
                                            "answer": r["answer"]})())
        return out

    async def set_staging_status(self, ids, status):
        for i in ids:
            self.status[i] = status

    async def list_all_questions(self):
        return []

    async def list_conversations_with_messages(self):
        return [(1, [type("M", (), {"role": "user", "content": "运费怎么算"})(),
                     type("M", (), {"role": "assistant", "content": "满99包邮"})()])]


@pytest.fixture
def fake_mine(monkeypatch):
    repo = _FakeRepo(None)
    monkeypatch.setattr(mining, "repository", repo)

    async def fake_extract(texts, model=None):
        return [mining.QaPair(question="运费怎么算", answer="满99包邮")]

    monkeypatch.setattr(mining, "extract_qa", fake_extract)
    return repo


async def test_mining_never_writes_directly_to_knowledge(fake_mine, monkeypatch):

    async def _boom(chunks):
        raise AssertionError("mine() 不许写知识库,入库只能走 /api/kb/staging/approve")

    monkeypatch.setattr(dualwrite, "write_pending", _boom)
    stats = await mining.mine()

    assert stats["kept"] == 1

    assert [s for s in fake_mine.status.values() if s == "kept"] == ["kept"]


async def test_mined_answers_remain_pending_review(fake_mine):
    await mining.mine()
    assert set(fake_mine.status.values()) == {"kept"}
    assert "approved" not in fake_mine.status.values()
