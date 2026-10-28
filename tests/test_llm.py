from app.config import settings
from app.core.llm import _thinking_kwargs, get_chat_model


def test_factory_points_to_chat_upstream():
    m = get_chat_model()
    assert m.model_name == settings.chat_model

    assert str(m.openai_api_base) == settings.chat_base_url


def test_factory_streaming_flag():
    assert get_chat_model(streaming=True).streaming is True


def test_empty_reasoning_controls_are_omitted(monkeypatch):

    for k in ("chat_thinking", "chat_reasoning_effort", "chat_reasoning_split"):
        monkeypatch.setattr(settings, k, "")
    assert _thinking_kwargs() == {}


def test_reasoning_disabled_uses_extra_body(monkeypatch):

    monkeypatch.setattr(settings, "chat_thinking", "disabled")
    monkeypatch.setattr(settings, "chat_reasoning_effort", "")
    monkeypatch.setattr(settings, "chat_reasoning_split", "")
    assert _thinking_kwargs() == {"extra_body": {"thinking": {"type": "disabled"}}}


def test_reasoning_effort_uses_standard_field(monkeypatch):
    monkeypatch.setattr(settings, "chat_thinking", "adaptive")
    monkeypatch.setattr(settings, "chat_reasoning_effort", "high")
    monkeypatch.setattr(settings, "chat_reasoning_split", "true")
    kw = _thinking_kwargs()
    assert kw["reasoning_effort"] == "high"
    assert kw["extra_body"]["thinking"] == {"type": "adaptive"}  # extra_body
    assert kw["extra_body"]["reasoning_split"] is True


def test_reasoning_split_accepts_boolean_spellings(monkeypatch):


    monkeypatch.setattr(settings, "chat_thinking", "")
    monkeypatch.setattr(settings, "chat_reasoning_effort", "")
    for v in ("true", "True", "1", "yes", "on", " TRUE "):
        monkeypatch.setattr(settings, "chat_reasoning_split", v)
        assert _thinking_kwargs()["extra_body"]["reasoning_split"] is True, v
    for v in ("false", "0", "no", "off"):
        monkeypatch.setattr(settings, "chat_reasoning_split", v)
        assert _thinking_kwargs()["extra_body"]["reasoning_split"] is False, v


def test_reasoning_configuration_reaches_model(monkeypatch):
    monkeypatch.setattr(settings, "chat_model", "MiniMax-M2")
    monkeypatch.setattr(settings, "chat_base_url", "https://api.example/v1")

    monkeypatch.setattr(settings, "chat_thinking", "disabled")
    monkeypatch.setattr(settings, "chat_reasoning_effort", "")
    monkeypatch.setattr(settings, "chat_reasoning_split", "")
    m = get_chat_model()
    assert m.extra_body == {"thinking": {"type": "disabled"}}
