from langchain_core.messages import AIMessageChunk

from app.core.llm import get_chat_model


def _feed(model, usages: list[dict]) -> dict:

    acc = None
    for u in usages:
        gc = model._convert_chunk_to_generation_chunk(
            {"choices": [{"index": 0, "delta": {"content": "x"}, "finish_reason": None}],
             "usage": u},
            AIMessageChunk, None)
        acc = gc.message if acc is None else acc + gc.message
    return acc.usage_metadata


def _cumulative(n: int, prompt: int) -> list[dict]:

    return [{"prompt_tokens": prompt, "completion_tokens": i,
             "total_tokens": prompt + i} for i in range(n)]


def test_repeated_cumulative_usage_aggregates_to_actual_total():
    m = get_chat_model()
    um = _feed(m, _cumulative(24, prompt=11))
    assert um["input_tokens"] == 11
    assert um["output_tokens"] == 23
    assert um["total_tokens"] == 34


def test_final_chunk_only_usage_remains_correct():

    m = get_chat_model()
    um = _feed(m, [{"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}])
    assert um["input_tokens"] == 100 and um["output_tokens"] == 20


def test_nested_usage_details_are_deltas():
    m = get_chat_model()
    usages = [{"prompt_tokens": 50, "completion_tokens": i, "total_tokens": 50 + i,
               "completion_tokens_details": {"reasoning_tokens": i}} for i in range(5)]
    um = _feed(m, usages)
    assert um["input_tokens"] == 50
    assert um["output_token_details"]["reasoning"] == 4


def test_usage_baseline_resets_between_streams():

    m = get_chat_model()
    first = _feed(m, _cumulative(5, prompt=11))
    second = _feed(m, _cumulative(5, prompt=11))
    assert second == first
