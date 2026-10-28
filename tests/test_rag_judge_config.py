from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import eval_rag, judge_check


async def test_rag_generation_selects_judge_for_both_scores(monkeypatch):
    calls = []

    def structured(schema, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise RuntimeError("judges-created")
        return object()

    monkeypatch.setattr(eval_rag, "get_chat_model", lambda: object())
    monkeypatch.setattr(eval_rag.llm, "structured", structured)
    with pytest.raises(RuntimeError, match="judges-created"):
        await eval_rag._generation([], {})
    assert calls == [{"temperature": 0, "slot": "judge"}] * 2


async def test_judge_regression_selects_judge(monkeypatch):
    row = SimpleNamespace(status="dismissed", citations=[{"answer": "evidence"}])
    monkeypatch.setattr(judge_check.repository, "list_faith_cases",
                        AsyncMock(return_value=([row], 1, {})))
    calls = []

    def structured(schema, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("judge-created")

    monkeypatch.setattr(judge_check.llm, "structured", structured)
    with pytest.raises(RuntimeError, match="judge-created"):
        await judge_check.main()
    assert calls == [{"temperature": 0, "slot": "judge"}]
