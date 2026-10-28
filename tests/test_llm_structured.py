import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from app.core import llm


class _Check(BaseModel):
    useful: bool = Field(description="证据是否足够")
    reason: str = Field(description="一句话理由")


def test_judge_structured_preserves_slot_and_temperature(fake):
    calls = fake()
    llm.structured(_Check, slot="judge", temperature=0)
    assert calls["kwargs"][0]["slot"] == "judge"
    assert calls["kwargs"][0]["temperature"] == 0


FC_OK = "ok"
FC_NONE = None
FC_PARSE_ERR = ValueError("Invalid JSON: arguments 被拼坏")
FC_TRANSIENT_ERR = TimeoutError("上游超时")


class _FakeModel:


    def __init__(self, fc, calls: dict):
        self.fc, self.calls = fc, calls

    def with_structured_output(self, schema, method=None):
        self.calls["methods"].append(method)

        def fc(_x):
            self.calls["function_calling"] += 1
            if isinstance(self.fc, BaseException):
                raise self.fc
            if self.fc is FC_NONE:
                return None
            return schema(useful=True, reason="function_calling")
        return RunnableLambda(fc)


@pytest.fixture
def fake(monkeypatch):
    def make(fc=FC_OK):
        calls = {"function_calling": 0, "kwargs": [], "methods": []}
        def factory(**kw):
            calls["kwargs"].append(kw)
            return _FakeModel(fc, calls)
        monkeypatch.setattr(llm, "get_chat_model", factory)
        return calls
    return make


async def test_valid_tool_calls_complete_without_retry(fake):
    calls = fake(FC_OK)
    r = await llm.structured(_Check, model="gpt-5.5").ainvoke("证据够不够")
    assert r.reason == "function_calling"
    assert calls["function_calling"] == 1


async def test_malformed_arguments_retry_then_raise(fake):


    calls = fake(FC_PARSE_ERR)
    with pytest.raises(ValueError):
        await llm.structured(_Check, model="claude-sonnet-5").ainvoke("证据够不够")
    assert calls["function_calling"] == 2
    assert "json_mode" not in calls["methods"]


async def test_missing_tool_calls_raise_instead_of_returning_none(fake):


    calls = fake(FC_NONE)
    with pytest.raises(OutputParserException):
        await llm.structured(_Check, model="claude-sonnet-5").ainvoke("证据够不够")
    assert calls["function_calling"] == 2


def test_sync_missing_tool_calls_raise(fake):
    calls = fake(FC_NONE)
    with pytest.raises(OutputParserException):
        llm.structured(_Check, model="claude-sonnet-5").invoke("证据够不够")
    assert calls["function_calling"] == 2


async def test_transient_failure_retries_without_contaminating_next_call(fake):


    calls = fake(FC_TRANSIENT_ERR)
    with pytest.raises(TimeoutError):
        await llm.structured(_Check, model="gpt-5.5").ainvoke("证据够不够")
    assert calls["function_calling"] == 2
    with pytest.raises(TimeoutError):
        await llm.structured(_Check, model="gpt-5.5").ainvoke("再来一次")
    assert calls["function_calling"] == 4


def test_structured_output_uses_only_function_calling(fake):


    calls = fake(FC_OK)
    llm.structured(_Check, model="gpt-5.5")
    assert calls["methods"] == ["function_calling"]


def test_streaming_is_enabled_by_default(fake):

    calls = fake(FC_OK)
    llm.structured(_Check, model="gpt-5.5")
    assert calls["kwargs"][-1]["streaming"] is True
    llm.structured(_Check, model="gpt-5.5", streaming=False)
    assert calls["kwargs"][-1]["streaming"] is False


def test_judge_temperature_reaches_model(fake):


    calls = fake(FC_OK)
    llm.structured(_Check, model="gpt-5.5", temperature=0)
    assert calls["kwargs"][-1]["temperature"] == 0
    llm.structured(_Check, model="gpt-5.5")
    assert calls["kwargs"][-1]["temperature"] is None


def test_default_temperature_and_explicit_zero():

    assert llm.get_chat_model().temperature == 0.3
    assert llm.get_chat_model(temperature=0).temperature == 0


def test_flagged_family_forces_non_streaming(monkeypatch):

    seen = {}

    def fake_get_chat_model(streaming=False, model=None, temperature=None, slot="chat", thinking=True):
        seen["streaming"] = streaming
        raise RuntimeError("stop-here")

    monkeypatch.setattr(llm, "get_chat_model", fake_get_chat_model)
    for name, expect in (("MiniMax-M3", False), ("deepseek-ai/DeepSeek-V4-Flash", True)):
        seen.clear()
        with pytest.raises(RuntimeError):
            llm.structured(_Check, model=name)
        assert seen["streaming"] is expect, f"{name} 的 streaming 应为 {expect}"


class _FlakyModel(_FakeModel):


    def __init__(self, misses: int, calls: dict):
        super().__init__(FC_OK, calls)
        self.misses = misses

    def with_structured_output(self, schema, method=None):
        self.calls["methods"].append(method)

        def fc(_x):
            self.calls["function_calling"] += 1
            if self.calls["function_calling"] <= self.misses:
                return None
            return schema(useful=True, reason="function_calling")
        return RunnableLambda(fc)


@pytest.fixture
def flaky(monkeypatch):
    def make(misses: int):
        calls = {"function_calling": 0, "kwargs": [], "methods": []}
        monkeypatch.setattr(llm, "get_chat_model", lambda **kw: _FlakyModel(misses, calls))
        return calls
    return make


async def test_missing_tool_call_recovers_on_retry(flaky):

    calls = flaky(misses=1)
    r = await llm.structured(_Check, model="flaky-model").ainvoke("证据够不够")
    assert r.reason == "function_calling"
    assert calls["function_calling"] == 2


async def test_retry_state_is_local_to_each_call(flaky):

    calls = flaky(misses=2)
    with pytest.raises(OutputParserException):
        await llm.structured(_Check, model="dead-model").ainvoke("x")
    assert calls["function_calling"] == 2

    r = await llm.structured(_Check, model="dead-model").ainvoke("x")
    assert r.reason == "function_calling"
