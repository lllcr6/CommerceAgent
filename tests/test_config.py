import pytest
from pydantic import ValidationError

from app.config import Settings


_REQUIRED = {
    "CHAT_MODEL": "deepseek-ai/DeepSeek-V4-Flash",
    "CHAT_BASE_URL": "https://api.siliconflow.cn/v1",
    "CHAT_API_KEY": "sk-test",
    "EMBED_API_KEY": "sk-test",
    "RERANK_API_KEY": "sk-test",
}


def _fill(monkeypatch, skip=None):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    for k, v in _REQUIRED.items():
        if k == skip:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


@pytest.mark.parametrize("missing", sorted(_REQUIRED))
def test_provider_identity_configuration_is_required(monkeypatch, missing):


    _fill(monkeypatch, skip=missing)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_embedding_and_reranking_endpoints_have_defaults(monkeypatch):

    _fill(monkeypatch)
    s = Settings(_env_file=None)
    assert s.embed_base_url == "https://api.siliconflow.cn/v1"
    assert s.rerank_base_url == "https://api.siliconflow.cn/v1"


def test_settings_defaults(monkeypatch):

    _fill(monkeypatch)
    s = Settings(_env_file=None)
    assert s.token_budget == 2000
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"


def test_settings_env_override(monkeypatch):
    _fill(monkeypatch)
    monkeypatch.setenv("TOKEN_BUDGET", "500")
    assert Settings(_env_file=None).token_budget == 500


def test_judge_env_override(monkeypatch):
    _fill(monkeypatch)
    monkeypatch.setenv("JUDGE_MODEL", "strong-judge")
    monkeypatch.setenv("JUDGE_BASE_URL", "https://judge.example/v1")
    monkeypatch.setenv("JUDGE_API_KEY", "sk-judge-test")
    s = Settings(_env_file=None)
    assert (s.judge_model, s.judge_base_url, s.judge_api_key) == (
        "strong-judge", "https://judge.example/v1", "sk-judge-test")
