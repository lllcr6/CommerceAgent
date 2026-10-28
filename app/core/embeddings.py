from urllib.parse import urlsplit
from openai import AsyncOpenAI
from app.config import settings
from app.core.service_errors import KnowledgeServiceError
from app.core.observability import record_aux_usage

_CLIENT: AsyncOpenAI | None = None

def _client() -> AsyncOpenAI:
    """Shared OpenAI-compatible embedding client; no vendor SDK required."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = AsyncOpenAI(base_url=settings.embed_base_url, api_key=settings.embed_api_key,
                             timeout=20, max_retries=2)
    return _CLIENT

def _batch_limit():
    host = (urlsplit(settings.embed_base_url).hostname or '').lower()
    alibaba = host.endswith('.maas.aliyuncs.com') or host in {'dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com','dashscope-us.aliyuncs.com'}
    if alibaba and settings.embed_model in {'text-embedding-v3','text-embedding-v4'}:
        return 10
    if alibaba and settings.embed_model.startswith('qwen3.7-text-embedding'):
        return 20
    return 64

async def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = []
    size = _batch_limit()
    try:
        for start in range(0,len(texts),size):
            batch = texts[start:start+size]
            resp = await _client().embeddings.create(model=settings.embed_model, input=batch,
                                                      encoding_format='float')
            usage = getattr(resp, 'usage', None)
            tokens = getattr(usage, 'prompt_tokens', None)
            if tokens is None:
                tokens = getattr(usage, 'total_tokens', None)
            if tokens is None:
                from app.core.memory import chars_to_tokens
                record_aux_usage('embedding', settings.embed_model, chars_to_tokens(sum(map(len,batch))), estimated=True)
            else:
                record_aux_usage('embedding', settings.embed_model, tokens)
            data = sorted(enumerate(resp.data), key=lambda item:getattr(item[1],'index',item[0]))
            if len(data) != len(batch):
                raise ValueError('Embedding response count does not match input')
            vectors.extend(d.embedding for _,d in data)
    except Exception as exc:
        raise KnowledgeServiceError('embedding') from exc
    return vectors

async def embed_query(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
