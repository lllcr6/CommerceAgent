"""A broken model call must not masquerade as an unrelated user question."""
import httpx
import pytest
from openai import NotFoundError,APIConnectionError
from langchain_core.runnables import RunnableLambda
from app.core import intent

@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[
    NotFoundError('wrong API path',response=httpx.Response(404,request=httpx.Request('POST','https://model.test/api/v1/chat/completions')),body={}),
    APIConnectionError(request=httpx.Request('POST','https://model.test/v1/chat/completions')),
])
async def test_upstream_failure_propagates(monkeypatch,failure):
    async def fail(_):raise failure
    monkeypatch.setattr(intent.llm,'structured',lambda *a,**kw:RunnableLambda(fail))
    with pytest.raises(type(failure)):
        await intent.classify('订单什么时候发货？')

@pytest.mark.asyncio
async def test_actual_other_intent_remains_script_route(monkeypatch):
    async def other(_):return intent._Intent(intent='other',confidence=.95)
    monkeypatch.setattr(intent.llm,'structured',lambda *a,**kw:RunnableLambda(other))
    assert await intent.classify('无关问题')=={'intent':'other','confidence':.95}
