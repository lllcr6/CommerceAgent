import pytest
from pydantic import ValidationError

from app.config import settings
from app.schemas.chat import ChatRequest


def test_normal_message_passes():
    req = ChatRequest(user_id="u1", message="Can I return the pet bed?")
    assert req.conversation_id is None


def test_oversized_message_rejected():

    huge = "订单详情" * 2000
    with pytest.raises(ValidationError) as e:
        ChatRequest(user_id="u1", message=huge)
    assert "too long" in str(e.value)


def test_limit_follows_config(monkeypatch):
    monkeypatch.setattr(settings, "max_user_input_tokens", 10)
    with pytest.raises(ValidationError):
        ChatRequest(user_id="u1", message="This message exceeds the configured input token budget. " * 5)
