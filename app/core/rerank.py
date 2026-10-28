import asyncio
import logging
import math
import random
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings
from app.core.service_errors import KnowledgeServiceError
from app.core.observability import record_aux_usage

_VERSION_SEG = re.compile(r"/v\d+$")
logger = logging.getLogger(__name__)


def _dashscope() -> bool:
    host = (urlsplit(settings.rerank_base_url).hostname or "").lower()
    return host.endswith(".maas.aliyuncs.com") or host in {
        "dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"}


def _rerank_url() -> str:
    """Resolve the configured provider endpoint, adding a version segment when required."""
    base = settings.rerank_base_url.rstrip("/")
    if _dashscope():
        u = urlsplit(base)
        return urlunsplit((u.scheme,u.netloc,"/api/v1/services/rerank/text-rerank/text-rerank","",""))
    if not _VERSION_SEG.search(base):
        base += "/v1"
    return base + "/rerank"


_RETRY_STATUS = {429, 500, 502, 503, 504}
_RETRIES = 4          # At most five attempts, including the initial request.
_BACKOFF = 2.0
_MAX_WAIT = 30.0
_BUDGET_CODES = {
    'budgetlimitexceeded', 'insufficientbalance', 'insufficient_balance',
    'arrearage', 'allocationquota.freetieronly', 'billing_hard_limit_reached',
    'insufficient_credits', 'credit_balance_too_low',
}


def _error_code(response):
    try:
        data = response.json()
        if not isinstance(data, dict):
            return ''
        error = data.get('error')
        code = error.get('code', '') if isinstance(error, dict) else data.get('code', '')
        # Log only short machine codes, never arbitrary response bodies or prompts.
        code = str(code)
        return code if re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', code) else ''
    except (ValueError, AttributeError):
        return ''


def _retry_after(response):
    value = getattr(response, 'headers', {}).get('Retry-After')
    if value is None:
        return None
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def _delay(attempt, response=None):
    base = min(_MAX_WAIT, _BACKOFF * 2 ** attempt)
    wait = min(_MAX_WAIT, base + random.uniform(0, base * 0.25))
    requested = _retry_after(response) if response is not None else None
    # Never retry earlier than the provider asks. Long cooldowns need a later Continue.
    if requested is not None:
        if requested > _MAX_WAIT:
            return None
        wait = max(wait, requested)
    return wait


async def _post(url, json, headers, timeout):
    """Retry transient failures with bounded exponential backoff and jitter.

    Explicit billing failures are terminal. Unknown 429s get bounded retries;
    the status alone cannot distinguish rate limits from a depleted budget.
    """
    for i in range(_RETRIES + 1):
        try:
            async with httpx.AsyncClient() as c:
                resp = await c.post(url, json=json, headers=headers, timeout=timeout)
        except httpx.TransportError as e:


            if i < _RETRIES:
                wait = _delay(i)
                logger.warning('Rerank transport failure (%s); retry %d/%d in %.2fs',
                               type(e).__name__, i + 1, _RETRIES, wait)
                await asyncio.sleep(wait)
                continue
            raise
        code = _error_code(resp) if resp.status_code >= 400 else ''
        if code.casefold() in _BUDGET_CODES:
            logger.error('Rerank provider rejected the request: HTTP %d, code=%s. '
                         'Budget or balance must be restored before continuing; not retrying.',
                         resp.status_code, code)
            return resp
        if resp.status_code not in _RETRY_STATUS:
            return resp
        if i == _RETRIES:
            logger.error('Rerank retries exhausted after %d attempts: HTTP %d, code=%s. '
                         'Completed evaluation calls remain saved for continuation.',
                         i + 1, resp.status_code, code or 'unknown')
            return resp
        wait = _delay(i, resp)
        if wait is None:
            logger.warning('Rerank provider requested a cooldown longer than %.0fs; '
                           'not retrying early. Continue evaluation after the cooldown. HTTP %d, code=%s',
                           _MAX_WAIT, resp.status_code, code or 'unknown')
            return resp
        logger.warning('Rerank HTTP %d, code=%s; retry %d/%d in %.2fs',
                       resp.status_code, code or 'unknown', i + 1, _RETRIES, wait)
        await asyncio.sleep(wait)


async def rerank(query: str, docs: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
    """Return document indices and relevance scores in descending order through the configured reranking API."""
    if not docs:
        return []
    payload = {"model": settings.rerank_model, "query": query, "documents": docs,
               "top_n": top_n or len(docs)}
    dashscope = _dashscope()
    if dashscope:
        payload = {"model": settings.rerank_model, "input": {"query": query, "documents": docs},
                   "parameters": {"top_n": top_n or len(docs), "return_documents": False}}
    try:
        resp = await _post(_rerank_url(), payload,
                           {"Authorization": f"Bearer {settings.rerank_api_key}"}, 60)
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage") or {}
        tokens = usage.get("input_tokens", usage.get("total_tokens"))
        if tokens is None:
            from app.core.memory import chars_to_tokens
            record_aux_usage("rerank", settings.rerank_model, chars_to_tokens(len(query)+sum(map(len,docs))), estimated=True)
        else:
            record_aux_usage("rerank", settings.rerank_model, tokens)
        results = data["output"]["results"] if dashscope else data["results"]
    except Exception as exc:
        raise KnowledgeServiceError("rerank") from exc
    ranked = sorted(((r["index"], float(r["relevance_score"])) for r in results),
                    key=lambda x: x[1], reverse=True)
    return ranked[:top_n] if top_n else ranked
