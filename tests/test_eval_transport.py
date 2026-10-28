from unittest.mock import AsyncMock

from app.eval_transport import evaluation_transport, model_transport
from app.core import llm
from scripts import eval_rag


def test_transport_is_scoped_and_model_settings_are_unchanged(monkeypatch):
    captured=[]
    def constructor(**kwargs):
        captured.append(kwargs)
        return kwargs
    monkeypatch.setattr(llm, '_CumulativeUsageChatOpenAI', constructor)
    ordinary=llm.get_chat_model()
    with evaluation_transport():
        evaluation=llm.get_chat_model()
        assert model_transport().structured_attempts == 1
    assert llm.get_chat_model() == ordinary
    assert ordinary['timeout'] == 20 and ordinary['max_retries'] == 2
    assert evaluation['timeout'] == 90 and evaluation['max_retries'] == 0
    assert {k:v for k,v in ordinary.items() if k not in ('timeout','max_retries')} == {
        k:v for k,v in evaluation.items() if k not in ('timeout','max_retries')}


async def test_evaluation_owns_retry_and_success_is_reused(tmp_path, monkeypatch):
    from app.kb.eval_checkpoint import Checkpoint
    from langchain_core.runnables import RunnableLambda
    calls=AsyncMock(side_effect=[TimeoutError(), eval_rag._Cov(covered_count=1)])
    runnable=RunnableLambda(lambda x: None, afunc=calls)
    class Model:
        def with_structured_output(self,*args,**kwargs): return runnable
    monkeypatch.setattr(llm,'get_chat_model',lambda **kwargs: Model())
    checkpoint=Checkpoint(tmp_path/'checkpoints','same')
    monkeypatch.setattr(eval_rag,'_checkpoint',checkpoint)
    monkeypatch.setattr(eval_rag,'_errs',[])
    monkeypatch.setattr(eval_rag.asyncio,'sleep',AsyncMock())
    with evaluation_transport():
        judge=llm.structured(eval_rag._Cov,slot='judge',temperature=0)
        factory=lambda: judge.ainvoke('test')
        assert await eval_rag._try(factory,'cov:vector:EN104') == eval_rag._Cov(covered_count=1)
        assert await eval_rag._try(factory,'cov:vector:EN104') == eval_rag._Cov(covered_count=1)
    assert calls.await_count == 2
    assert checkpoint.saved == 1
    assert eval_rag._errs == []


async def test_chart_notes_never_request_models(monkeypatch):
    provider=AsyncMock(side_effect=AssertionError('No paid chart notes'))
    monkeypatch.setattr(eval_rag.read_notes,'generate',provider)
    monkeypatch.setattr(eval_rag,'_checkpoint',None)
    data={s:{b:None for b in eval_rag.GRADED_BUCKETS+['overall']} for s in eval_rag.STRATEGIES}
    assert await eval_rag._read_notes(data,data,None) == {}
    provider.assert_not_called()
