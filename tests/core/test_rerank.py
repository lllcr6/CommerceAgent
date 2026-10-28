import pytest

from app.config import settings
from app.core import rerank as rr


@pytest.fixture(autouse=True)
def compatible_rerank_endpoint(monkeypatch):
    # These unit cases exercise the generic protocol, independent of local .env.
    monkeypatch.setattr(settings, "rerank_base_url", "https://api.siliconflow.cn/v1")


async def _noop_sleep(_):

    return None


@pytest.mark.parametrize("base, want", [

    ("https://api.siliconflow.cn/v1", "https://api.siliconflow.cn/v1/rerank"),
    ("https://api.siliconflow.cn/v1/", "https://api.siliconflow.cn/v1/rerank"),


    ("https://api.siliconflow.cn", "https://api.siliconflow.cn/v1/rerank"),
    ("https://api.siliconflow.cn/", "https://api.siliconflow.cn/v1/rerank"),

    ("https://api.cohere.com/v2", "https://api.cohere.com/v2/rerank"),
])
def test_rerank_endpoint_accepts_optional_version(monkeypatch, base, want):
    monkeypatch.setattr(settings, "rerank_base_url", base)
    assert rr._rerank_url() == want


def test_rerank_endpoint_is_resolved_per_request(monkeypatch):

    monkeypatch.setattr(settings, "rerank_base_url", "https://a.example.com/v1")
    first = rr._rerank_url()
    monkeypatch.setattr(settings, "rerank_base_url", "https://b.example.com/v1")
    assert first != rr._rerank_url() == "https://b.example.com/v1/rerank"


@pytest.mark.asyncio
async def test_rerank_orders_and_truncates(monkeypatch):
    async def fake_post(url, json, headers, timeout):
        class R:
            def raise_for_status(self): pass
            def json(self):
                return {"results": [
                    {"index": 0, "relevance_score": 0.1},
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 2, "relevance_score": 0.5},
                ]}
        return R()
    monkeypatch.setattr("app.core.rerank._post", fake_post)
    out = await rr.rerank("q", ["a", "b", "c"], top_n=2)
    assert out == [(1, 0.9), (2, 0.5)]


@pytest.mark.asyncio
async def test_rerank_empty_docs():
    assert await rr.rerank("q", []) == []


async def test_transport_failures_retry_with_backoff(monkeypatch):

    calls = {"n": 0}

    class _Resp:
        status_code = 200

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise rr.httpx.RemoteProtocolError("Server disconnected")
            return _Resp()

    monkeypatch.setattr(rr.httpx, "AsyncClient", lambda *a, **kw: _Client())
    monkeypatch.setattr(rr.asyncio, "sleep", _noop_sleep)

    resp = await rr._post("http://x/rerank", {}, {}, 5)
    assert resp.status_code == 200
    assert calls["n"] == 2


async def test_exhausted_transport_retries_raise(monkeypatch):

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise rr.httpx.ConnectError("connection refused")

    monkeypatch.setattr(rr.httpx, "AsyncClient", lambda *a, **kw: _Client())
    monkeypatch.setattr(rr.asyncio, "sleep", _noop_sleep)

    with pytest.raises(rr.httpx.ConnectError):
        await rr._post("http://x/rerank", {}, {}, 5)


def mock_provider(monkeypatch, responses):
    import httpx
    from unittest.mock import AsyncMock
    attempts = []
    iterator = iter(responses)
    client_type = httpx.AsyncClient
    def handler(request):
        attempts.append(request)
        return next(iterator)
    monkeypatch.setattr(rr.httpx, 'AsyncClient', lambda: client_type(transport=httpx.MockTransport(handler)))
    sleep = AsyncMock()
    monkeypatch.setattr(rr.asyncio, 'sleep', sleep)
    monkeypatch.setattr(rr.random, 'uniform', lambda a, b: 0)
    return attempts, sleep


async def test_rate_limit_retries_exponentially_then_succeeds(monkeypatch, caplog):
    import httpx
    attempts, sleep = mock_provider(monkeypatch, [
        httpx.Response(429, json={'code': 'Throttling.RateQuota'}) for _ in range(3)
    ] + [httpx.Response(200, json={'results': []})])
    response = await rr._post('https://example.test/rerank', {}, {}, 1)
    assert response.status_code == 200
    assert len(attempts) == 4
    assert [call.args[0] for call in sleep.await_args_list] == [2, 4, 8]
    assert 'retry 3/4' in caplog.text


async def test_retries_are_bounded_and_return_last_error(monkeypatch):
    import httpx
    attempts, sleep = mock_provider(monkeypatch, [httpx.Response(503) for _ in range(5)])
    response = await rr._post('https://example.test/rerank', {}, {}, 1)
    assert response.status_code == 503
    assert len(attempts) == 5
    assert [call.args[0] for call in sleep.await_args_list] == [2, 4, 8, 16]
    with pytest.raises(httpx.HTTPStatusError):
        response.raise_for_status()


@pytest.mark.parametrize('body', [
    {'code': 'BudgetLimitExceeded'}, {'error': {'code': 'InsufficientBalance'}},
    {'error': {'code': 'billing_hard_limit_reached'}},
    {'code': 'AllocationQuota.FreeTierOnly'},
])
async def test_budget_exhaustion_is_not_retried(monkeypatch, body, caplog):
    import httpx
    attempts, sleep = mock_provider(monkeypatch, [httpx.Response(429, json=body)])
    response = await rr._post('https://example.test/rerank', {}, {}, 1)
    assert response.status_code == 429
    assert len(attempts) == 1
    sleep.assert_not_awaited()
    assert 'not retrying' in caplog.text


async def test_retry_after_is_respected(monkeypatch):
    import httpx
    attempts, sleep = mock_provider(monkeypatch, [
        httpx.Response(429, headers={'Retry-After': '12'}), httpx.Response(200)])
    await rr._post('https://example.test/rerank', {}, {}, 1)
    assert sleep.await_args.args == (12.0,)
    assert len(attempts) == 2


async def test_long_retry_after_does_not_retry_early(monkeypatch):
    import httpx
    attempts, sleep = mock_provider(monkeypatch, [httpx.Response(429, headers={'Retry-After': '120'})])
    response = await rr._post('https://example.test/rerank', {}, {}, 1)
    assert response.status_code == 429
    assert len(attempts) == 1
    sleep.assert_not_awaited()


def test_retry_after_http_date_and_invalid_values():
    import httpx
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20), usegmt=True)
    assert 18 < rr._retry_after(httpx.Response(429, headers={'Retry-After': future})) <= 20
    for value in ['bad', 'nan', 'inf']:
        assert rr._retry_after(httpx.Response(429, headers={'Retry-After': value})) is None


async def test_nonretryable_http_error_has_no_retry(monkeypatch):
    import httpx
    attempts, sleep = mock_provider(monkeypatch, [httpx.Response(401)])
    assert (await rr._post('https://example.test/rerank', {}, {}, 1)).status_code == 401
    assert len(attempts) == 1
    sleep.assert_not_awaited()


def test_jitter_and_backoff_are_bounded(monkeypatch):
    monkeypatch.setattr(rr.random, 'uniform', lambda a, b: b)
    assert [rr._delay(n) for n in range(4)] == [2.5, 5, 10, 20]
    assert rr._delay(10) == 30


async def test_cancel_during_backoff_does_not_make_more_requests(monkeypatch):
    import asyncio
    import httpx
    attempts, sleep = mock_provider(monkeypatch, [httpx.Response(429)])
    sleep.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await rr._post('https://example.test/rerank', {}, {}, 1)
    assert len(attempts) == 1


async def test_retry_logs_do_not_include_response_body_or_credentials(monkeypatch, caplog):
    import httpx
    attempts, sleep = mock_provider(monkeypatch, [
        httpx.Response(429, json={'code': 'invalid code SECRET', 'message': 'private document SECRET'}),
        httpx.Response(200)])
    await rr._post('https://example.test/rerank', {'query': 'SECRET'}, {'Authorization': 'Bearer SECRET'}, 1)
    assert 'SECRET' not in caplog.text
