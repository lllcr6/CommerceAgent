import logging

from langchain_core.exceptions import OutputParserException
from langchain_openai import ChatOpenAI
from pydantic import PrivateAttr

from app.config import settings
from app.eval_transport import model_transport

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def _diff_usage(cur: dict, prev: dict) -> dict:
    """Convert cumulative streaming usage, including nested detail fields, to per-chunk deltas."""
    out: dict = {}
    for k, v in cur.items():
        p = prev.get(k)
        if isinstance(v, dict):
            out[k] = _diff_usage(v, p if isinstance(p, dict) else {})
        elif isinstance(v, (int, float)):
            out[k] = max(0, v - (p if isinstance(p, (int, float)) else 0))
        else:
            out[k] = v
    return out


class _CumulativeUsageChatOpenAI(ChatOpenAI):
    """Convert repeated cumulative usage to deltas before LangChain aggregates chunks. Providers reporting usage only at the end remain supported."""

    _prev_usage: dict = PrivateAttr(default_factory=dict)

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        usage = chunk.get("usage") if isinstance(chunk, dict) else None
        if usage:
            prev = self._prev_usage


            if any(isinstance(v, (int, float)) and v < prev.get(k, 0)
                   for k, v in usage.items() if not isinstance(v, dict)):
                prev = {}
            chunk = {**chunk, "usage": _diff_usage(usage, prev)}
            self._prev_usage = usage
        return super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info)


def resolve_slot(slot: str = "chat") -> tuple[str, str, str]:
    """Resolve model, endpoint, and key per purpose; each missing value inherits its CHAT setting."""
    if slot == "chat":
        return settings.chat_model, settings.chat_base_url, settings.chat_api_key
    return (
        getattr(settings, f"{slot}_model", "") or settings.chat_model,
        getattr(settings, f"{slot}_base_url", "") or settings.chat_base_url,
        getattr(settings, f"{slot}_api_key", "") or settings.chat_api_key,
    )


def get_chat_model(streaming: bool = False, model: str | None = None,
                   temperature: float | None = None, slot: str = "chat",
                   thinking: bool = True) -> ChatOpenAI:
    """Construct the configured OpenAI-compatible chat model with streaming usage. Judges explicitly use temperature zero. Dedicated reasoning controls are provider-specific."""
    slot_model, base_url, api_key = resolve_slot(slot)
    thinking_kw = _model_thinking_kwargs(model or slot_model, base_url, thinking=thinking)
    return _CumulativeUsageChatOpenAI(
        model=model or slot_model,
        base_url=base_url,
        api_key=api_key,
        streaming=streaming,
        stream_usage=True,
        max_retries=model_transport().max_retries,
        timeout=model_transport().timeout,
        max_tokens=settings.max_output_tokens,
        temperature=0.3 if temperature is None else temperature,
        **thinking_kw,
    )


def _model_thinking_kwargs(model: str, base_url: str, *, thinking: bool = True) -> dict:
    """Keep OpenAI transport generic; adapt only known provider-specific options.

    Qwen3 on Alibaba uses enable_thinking, while MiniMax and DeepSeek accept
    thinking.type. Select against the resolved slot, not the global chat model.
    """
    from urllib.parse import urlsplit
    host = (urlsplit(base_url).hostname or "").lower()
    alibaba = host.endswith(".maas.aliyuncs.com") or host in {
        "dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"}
    qwen3 = (model or "").lower().split("/")[-1].startswith("qwen3")
    if not (alibaba and qwen3):
        if thinking:
            return _thinking_kwargs()
        if any(family in (model or "").lower() for family in ("deepseek", "minimax")):
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        # Plain OpenAI-compatible providers need no proprietary thinking switch.
        return {}
    extra = {}
    mode = settings.chat_thinking.strip().lower()
    if not thinking or mode == "disabled":
        extra["enable_thinking"] = False
    elif mode == "enabled":
        extra["enable_thinking"] = True
    # adaptive / empty: keep Qwen's own default; never send MiniMax's thinking
    # or reasoning_split fields. They are not portable OpenAI parameters.
    kwargs = {"extra_body": extra} if extra else {}
    if settings.chat_reasoning_effort:
        kwargs["reasoning_effort"] = settings.chat_reasoning_effort
    return kwargs


def _thinking_kwargs() -> dict:

    """Build explicit reasoning controls, omitting unset fields. Provider extensions use extra_body; reasoning_effort uses the standard field. Known provider differences are adapted separately."""
    kwargs: dict = {}
    extra: dict = {}
    if settings.chat_thinking:
        extra["thinking"] = {"type": settings.chat_thinking}
    if settings.chat_reasoning_split:


        extra["reasoning_split"] = settings.chat_reasoning_split.strip().lower() in _TRUTHY
    if extra:
        kwargs["extra_body"] = extra
    if settings.chat_reasoning_effort:
        kwargs["reasoning_effort"] = settings.chat_reasoning_effort
    return kwargs


#


#


#


#


_NO_STREAM_TOOLCALL_FAMILIES: tuple[str, ...] = ("minimax",)


def needs_non_streaming_tools(model: str | None = None, slot: str = "chat") -> bool:
    name = (model or resolve_slot(slot)[0] or "").lower()
    return any(f in name for f in _NO_STREAM_TOOLCALL_FAMILIES)


def structured(schema, *, model: str | None = None, streaming: bool = True,
               temperature: float | None = None, slot: str = "chat"):

    """Use function calling for structured output, with streaming enabled by default. Retry a transient malformed or missing tool call once, then propagate failure to the caller. Judges explicitly request temperature zero."""
    from langchain_core.runnables import RunnableLambda

    slot_model, slot_base, _ = resolve_slot(slot)
    name = (model or slot_model or "").lower()
    if needs_non_streaming_tools(model, slot=slot):
        streaming = False
    m = get_chat_model(streaming=streaming, model=model, temperature=temperature,
                       slot=slot, thinking=False)
    fc = m.with_structured_output(schema, method="function_calling")

    attempts = model_transport().structured_attempts

    def _log(attempt: int, why: str) -> None:
        logger.warning("Structured output failed: model=%s attempt=%s/%s error=%s; %s",
                       name, attempt, attempts, why,
                       "retrying" if attempt < attempts else "returning to caller")

    def _no_tool_calls() -> OutputParserException:
        return OutputParserException(f"{name} returned no tool calls after {attempts} attempts")

    def _run(x):
        for attempt in range(1, attempts + 1):
            try:
                r = fc.invoke(x)
            except Exception as e:
                _log(attempt, type(e).__name__)
                if attempt == attempts:
                    raise
                continue
            if r is not None:
                return r
            _log(attempt, "no tool calls")
        raise _no_tool_calls()

    async def _arun(x):
        for attempt in range(1, attempts + 1):
            try:
                r = await fc.ainvoke(x)
            except Exception as e:
                _log(attempt, type(e).__name__)
                if attempt == attempts:
                    raise
                continue
            if r is not None:
                return r
            _log(attempt, "no tool calls")
        raise _no_tool_calls()

    return RunnableLambda(_run, afunc=_arun)
