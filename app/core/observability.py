import logging

from app.config import settings

logger = logging.getLogger(__name__)
_client = None


def langfuse_enabled() -> bool:
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key
                and settings.langfuse_base_url)


def _init_client():

    """Initialize or reuse the Langfuse singleton."""
    global _client
    if _client is None:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
        )
    return _client


def _make_handler():
    from langfuse.langchain import CallbackHandler

    class _InlineCallbackHandler(CallbackHandler):

        """Execute callbacks inline so OpenTelemetry context remains in the calling task and intent tags reach the current trace."""
        run_inline = True

    return _InlineCallbackHandler()


def get_langfuse():

    """Return the initialized optional tracing client, or None when tracing is disabled."""
    if not langfuse_enabled():
        return None
    return _init_client()


def record_aux_usage(name: str, model: str, input_tokens: int | None, *, estimated: bool = False) -> None:
    """Record provider-reported embedding/reranking usage on the active Agent trace.

    These services bypass LangChain callbacks. Callers label fallback estimates explicitly;
    offline evaluations do not create standalone traces.
    """
    from app.usage_store import record_aux
    record_aux(name, model, input_tokens, estimated)
    if not langfuse_enabled():
        return
    try:
        from opentelemetry.trace import get_current_span
        if not get_current_span().get_span_context().is_valid:
            return
        client = get_langfuse()
        if not client.get_current_trace_id():
            return
        observation = client.start_observation(
            name=name, as_type="embedding" if name == "embedding" else "generation",
            model=model,
            usage_details={"input": input_tokens, "output": 0} if input_tokens is not None else None,
            metadata={"usage_source": "estimated_4_chars" if estimated else "provider_response", "usage_missing": estimated or input_tokens is None})
        observation.end()
    except Exception:
        logger.warning("Auxiliary model usage recording failed; reply is unaffected", exc_info=True)


def attach_observability(graph):

    """Attach the graph callback once after compilation; leave the graph unchanged when tracing is unconfigured."""
    if not langfuse_enabled():
        return graph
    _init_client()
    return graph.with_config({"callbacks": [_make_handler()]})


def tag_intent(intent: str, confidence: float) -> None:

    if not langfuse_enabled():
        return
    try:
        from langfuse import get_client, propagate_attributes


        with propagate_attributes(
            metadata={"intent": intent, "intent_confidence": f"{confidence:.2f}"},
            tags=[f"intent:{intent}"],
        ):
            get_client().create_event(name="intent-tagged")
    except Exception:
        logger.warning("Langfuse intent tagging failed; ignored", exc_info=True)
