from app.core.llm import get_chat_model


def test_streaming_model_requests_usage():
    m = get_chat_model(streaming=True)
    assert m.stream_usage is True


def test_non_streaming_model_also_flags_usage():
    assert get_chat_model().stream_usage is True
