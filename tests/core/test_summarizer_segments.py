import pytest

from app.config import settings
from app.core import summarizer


class _Conv:
    def __init__(self, upto=0, layer1=0):
        self.summary_upto_msg_id = upto
        self.layer1_from_msg_id = layer1


class _Msg:
    def __init__(self, mid, content, role="user"):
        self.id, self.content, self.role = mid, content, role


@pytest.mark.asyncio
async def test_layer2_over_budget_triggers(monkeypatch):

    msgs = [_Msg(i, "evidence " * 400) for i in range(1, 21)]
    monkeypatch.setattr(summarizer.repository, "list_dialog_messages",
                        lambda cid: _async(msgs))
    monkeypatch.setattr(summarizer.repository, "count_messages_after",
                        lambda cid, upto: _async(0))
    monkeypatch.setattr(settings, "layer1_ratio", 0.7)
    monkeypatch.setattr(summarizer.budget, "compute", lambda: _Budget(10_000))
    assert await summarizer._should_summarize(1, _Conv(upto=0, layer1=20))


@pytest.mark.asyncio
async def test_empty_compressed_history_ignores_message_count(monkeypatch):

    monkeypatch.setattr(summarizer.repository, "list_dialog_messages", lambda cid: _async([]))
    assert not await summarizer._should_summarize(1, _Conv())


class _Budget:
    def __init__(self, sliding):
        self.sliding = sliding


async def _async(v):
    return v
