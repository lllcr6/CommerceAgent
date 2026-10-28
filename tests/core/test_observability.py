from app.core import observability


def test_disabled_when_keys_missing(monkeypatch):
    monkeypatch.setattr("app.config.settings.langfuse_public_key", "")
    monkeypatch.setattr("app.config.settings.langfuse_secret_key", "sk")
    monkeypatch.setattr("app.config.settings.langfuse_base_url", "http://x")
    assert observability.langfuse_enabled() is False


def test_attach_returns_graph_unchanged_when_disabled(monkeypatch):
    monkeypatch.setattr("app.config.settings.langfuse_public_key", "")
    sentinel = object()
    assert observability.attach_observability(sentinel) is sentinel


def test_tag_intent_noop_when_disabled(monkeypatch):
    monkeypatch.setattr("app.config.settings.langfuse_public_key", "")
    observability.tag_intent("商品咨询", 0.9)


def test_get_langfuse_none_when_disabled(monkeypatch):
    monkeypatch.setattr("app.config.settings.langfuse_public_key", "")
    assert observability.get_langfuse() is None


def test_attach_wraps_with_callbacks_when_enabled(monkeypatch):
    monkeypatch.setattr("app.config.settings.langfuse_public_key", "pk")
    monkeypatch.setattr("app.config.settings.langfuse_secret_key", "sk")
    monkeypatch.setattr("app.config.settings.langfuse_base_url", "http://localhost:3000")

    calls = {}

    class FakeGraph:
        def with_config(self, cfg):
            calls["cfg"] = cfg
            return "wrapped"

    monkeypatch.setattr(observability, "_init_client", lambda: object())
    monkeypatch.setattr(observability, "_make_handler", lambda: "HANDLER")
    assert observability.attach_observability(FakeGraph()) == "wrapped"
    assert calls["cfg"] == {"callbacks": ["HANDLER"]}


def test_aux_usage_records_provider_tokens_without_inventing_missing_usage(monkeypatch):
    from types import SimpleNamespace
    from app.core import observability
    import opentelemetry.trace
    seen=[]
    class Client:
        def get_current_trace_id(self):return 'test-trace'
        def start_observation(self,**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(end=lambda:None)
    monkeypatch.setattr(observability,'langfuse_enabled',lambda:True)
    monkeypatch.setattr(observability,'get_langfuse',lambda:Client())
    monkeypatch.setattr(opentelemetry.trace,'get_current_span',lambda:SimpleNamespace(
        get_span_context=lambda:SimpleNamespace(is_valid=True)))
    observability.record_aux_usage('embedding','text-embedding-v4',4)
    observability.record_aux_usage('rerank','qwen3-rerank',None)
    assert seen[0]['usage_details']=={'input':4,'output':0}
    assert seen[0]['as_type']=='embedding'
    assert seen[1]['usage_details'] is None
    assert seen[1]['metadata']['usage_missing'] is True
