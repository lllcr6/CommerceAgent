from app.config import settings
from app.core.llm import get_chat_model, needs_non_streaming_tools, resolve_slot


def test_chat_slot_reads_chat_group():
    model, base, key = resolve_slot("chat")
    assert (model, base, key) == (
        settings.chat_model, settings.chat_base_url, settings.chat_api_key)


def test_empty_slot_falls_back_to_chat(monkeypatch):

    monkeypatch.setattr(settings, "intent_model", "")
    monkeypatch.setattr(settings, "intent_base_url", "")
    monkeypatch.setattr(settings, "intent_api_key", "")
    assert resolve_slot("intent") == (
        settings.chat_model, settings.chat_base_url, settings.chat_api_key)


def test_slot_overrides_are_independent(monkeypatch):

    monkeypatch.setattr(settings, "intent_model", "small-model")
    monkeypatch.setattr(settings, "intent_base_url", "")
    monkeypatch.setattr(settings, "intent_api_key", "")
    assert resolve_slot("intent") == (
        "small-model", settings.chat_base_url, settings.chat_api_key)

    monkeypatch.setattr(settings, "summary_base_url", "https://other.example/v1")
    monkeypatch.setattr(settings, "summary_api_key", "sk-other")
    monkeypatch.setattr(settings, "summary_model", "")
    assert resolve_slot("summary") == (
        settings.chat_model, "https://other.example/v1", "sk-other")


def test_needs_non_streaming_tools_reads_slot(monkeypatch):

    monkeypatch.setattr(settings, "intent_model", "MiniMax-M3")
    assert needs_non_streaming_tools(slot="intent")
    monkeypatch.setattr(settings, "intent_model", "deepseek-v4-flash")
    assert not needs_non_streaming_tools(slot="intent")


def test_needs_non_streaming_tools_explicit_model_wins():
    assert needs_non_streaming_tools("MiniMax-M2.7")
    assert not needs_non_streaming_tools("gpt-4o")


def test_judge_slot_fallback_and_model_only_override(monkeypatch):
    for field in ("judge_model", "judge_base_url", "judge_api_key"):
        monkeypatch.setattr(settings, field, "")
    assert resolve_slot("judge") == resolve_slot("chat")
    monkeypatch.setattr(settings, "judge_model", "strong-judge")
    assert resolve_slot("judge") == (
        "strong-judge", settings.chat_base_url, settings.chat_api_key)


def test_judge_uses_independent_upstream(monkeypatch):
    monkeypatch.setattr(settings, "judge_model", "strong-judge")
    monkeypatch.setattr(settings, "judge_base_url", "https://judge.example/v1")
    monkeypatch.setattr(settings, "judge_api_key", "sk-judge-test")
    model = get_chat_model(slot="judge", temperature=0, thinking=False)
    assert model.model_name == "strong-judge"
    assert str(model.openai_api_base) == "https://judge.example/v1"
    assert model.openai_api_key.get_secret_value() == "sk-judge-test"
    assert model.temperature == 0
    assert get_chat_model().model_name == settings.chat_model
