from uuid import uuid4
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from app import usage_store as store

@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(store,'PATH',tmp_path/'usage.sqlite')

def turn(cid, user='alice', usage=None):
    callback=store.UsageCallback(cid,user)
    root, call=uuid4(),uuid4()
    callback.on_chain_start(None,{},run_id=root)
    callback.on_chat_model_start({},[[HumanMessage(content='abcd')]],run_id=call,invocation_params={'model':'unknown-price-model'})
    msg=AIMessage(content='ok',usage_metadata=usage)
    callback.on_llm_end(SimpleNamespace(generations=[[SimpleNamespace(message=msg)]],llm_output=None),run_id=call)
    callback.on_chain_end({'intent':'product_question'},run_id=root)
    return callback

def test_actual_zero_usage_and_synthetic_exclusion():
    turn(1,usage={'input_tokens':0,'output_tokens':0,'total_tokens':0})
    turn(2,'bench_example',usage={'input_tokens':100,'output_tokens':30,'total_tokens':130})
    report=store.intent_report()
    assert report['total_tokens']==0
    assert report['total_requests']==1
    assert report['rows'][0]['estimated_or_missing_calls']==0
    assert store.session_usage(2)['calls'][0]['input']==100

def test_fallback_is_marked_and_has_no_prompts():
    turn(1)
    data=store.session_usage(1)
    assert data['calls'][0]['source']=='estimated_4_chars'
    assert 'abcd' not in str(data)
    assert store.intent_report()['rows'][0]['estimated_or_missing_calls']==1

async def test_benchmark_uses_local_usage_without_langfuse(monkeypatch):
    from scripts.benchmarks import agent_performance as agent
    for _ in range(3):turn(1,'bench_test',{'input_tokens':100,'output_tokens':20,'total_tokens':120})
    monkeypatch.setattr(agent.settings,'langfuse_public_key','')
    result=await agent.collect_usage([1],{'models':{}})
    assert result['1']['source']=='local_backend'
    assert result['1']['token_complete']
    assert result['1']['provider_input_tokens']==300
    assert result['1']['provider_output_tokens']==60
    assert len(result['1']['trace_ids'])==3

async def test_local_callback_records_real_chain_without_langfuse(monkeypatch):
    from langchain_core.runnables import RunnableLambda
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from app.config import settings
    monkeypatch.setattr(settings,'langfuse_public_key','')
    model=FakeMessagesListChatModel(responses=[AIMessage(content='ok',usage_metadata={'input_tokens':8,'output_tokens':2,'total_tokens':10})])
    async def step(value):
        await model.ainvoke('hello')
        return {'intent':'product_question'}
    callback=store.UsageCallback(9,'bench_callback')
    await RunnableLambda(step).ainvoke({},config={'callbacks':[callback]})
    data=store.session_usage(9)
    assert len(data['calls'])==1
    assert data['calls'][0]['input']==8
    assert data['calls'][0]['output']==2
    assert data['turns'][0]['status']=='completed'
    assert data['turns'][0]['intent']=='product_question'
    assert store.intent_report()['total_requests']==0
