"""Provider options must not break the shared OpenAI-compatible transport."""
import pytest
from app.config import settings
from app.core.llm import get_chat_model, _model_thinking_kwargs

@pytest.fixture(autouse=True)
def clean_options(monkeypatch):
    for key in ('chat_thinking','chat_reasoning_split','chat_reasoning_effort'):
        monkeypatch.setattr(settings,key,'')

@pytest.mark.parametrize('base',['https://example.test/v1','https://api.openai.com/v1'])
def test_standard_compatible_model_has_no_vendor_fields(monkeypatch,base):
    monkeypatch.setattr(settings,'chat_model','generic-tool-model')
    monkeypatch.setattr(settings,'chat_base_url',base)
    monkeypatch.setattr(settings,'chat_api_key','test-key')
    for thinking in [True,False]:
        model=get_chat_model(thinking=thinking)
        assert str(model.openai_api_base)==base
        assert not model.extra_body

@pytest.mark.parametrize('base',['https://ws-demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1','https://dashscope.aliyuncs.com/compatible-mode/v1'])
def test_qwen_drops_minimax_options_and_disables_structured_thinking(monkeypatch,base):
    monkeypatch.setattr(settings,'chat_thinking','adaptive')
    monkeypatch.setattr(settings,'chat_reasoning_split','true')
    assert _model_thinking_kwargs('qwen3.7-plus',base)=={}
    assert _model_thinking_kwargs('qwen3.7-plus',base,thinking=False)=={'extra_body':{'enable_thinking':False}}
    monkeypatch.setattr(settings,'chat_thinking','disabled')
    assert _model_thinking_kwargs('qwen3.7-plus',base)=={'extra_body':{'enable_thinking':False}}
    monkeypatch.setattr(settings,'chat_thinking','enabled')
    assert _model_thinking_kwargs('qwen3.7-plus',base)=={'extra_body':{'enable_thinking':True}}

def test_slot_resolved_provider_controls_options(monkeypatch):
    monkeypatch.setattr(settings,'chat_model','MiniMax-M3')
    monkeypatch.setattr(settings,'chat_base_url','https://example.test/v1')
    monkeypatch.setattr(settings,'chat_thinking','adaptive')
    monkeypatch.setattr(settings,'chat_reasoning_split','true')
    monkeypatch.setattr(settings,'intent_model','qwen3.7-plus')
    monkeypatch.setattr(settings,'intent_base_url','https://ws-demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
    assert get_chat_model(slot='intent',thinking=False).extra_body=={'enable_thinking':False}
    assert get_chat_model().extra_body=={'thinking':{'type':'adaptive'},'reasoning_split':True}

@pytest.mark.parametrize('name',['deepseek-v4-flash','MiniMax-M3'])
def test_existing_thinking_protocol_preserved(name):
    assert _model_thinking_kwargs(name,'https://example.test/v1',thinking=False)=={'extra_body':{'thinking':{'type':'disabled'}}}
