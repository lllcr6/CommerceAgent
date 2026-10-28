import pytest
from types import SimpleNamespace
from app.config import settings
from app.core import embeddings,rerank
from app.core.service_errors import KnowledgeServiceError

@pytest.mark.asyncio
async def test_dashscope_embedding_batches_and_order(monkeypatch):
    monkeypatch.setattr(settings,'embed_base_url','https://ws-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
    monkeypatch.setattr(settings,'embed_model','text-embedding-v4')
    calls=[]
    async def create(model,input,encoding_format):
        calls.append(len(input))
        assert encoding_format=='float'
        return SimpleNamespace(data=[SimpleNamespace(index=i,embedding=[int(t)]) for i,t in reversed(list(enumerate(input)))])
    monkeypatch.setattr(embeddings,'_client',lambda:SimpleNamespace(embeddings=SimpleNamespace(create=create)))
    out=await embeddings.embed_texts([str(i) for i in range(23)])
    assert calls==[10,10,3] and out==[[i] for i in range(23)]
    assert await embeddings.embed_texts([])==[]

@pytest.mark.asyncio
async def test_embedding_failure_is_not_chat_model_failure(monkeypatch):
    async def create(**kw):raise RuntimeError('upstream unavailable')
    monkeypatch.setattr(embeddings,'_client',lambda:SimpleNamespace(embeddings=SimpleNamespace(create=create)))
    with pytest.raises(KnowledgeServiceError,match='embedding service') as error:
        await embeddings.embed_query('question')
    assert isinstance(error.value.__cause__,RuntimeError)

@pytest.mark.asyncio
async def test_native_dashscope_rerank_and_generic_compatible(monkeypatch):
    for base,native in [('https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1',True),('https://example.test/v1',False)]:
        monkeypatch.setattr(settings,'rerank_base_url',base)
        async def post(url,json,headers,timeout):
            if native:
                assert url.endswith('/api/v1/services/rerank/text-rerank/text-rerank')
                assert json['input']=={'query':'q','documents':['a','b']}
                assert json['parameters']['top_n']==1
            else:
                assert url=='https://example.test/v1/rerank'
                assert json['query']=='q' and json['documents']==['a','b']
            data={'results':[{'index':1,'relevance_score':.9},{'index':0,'relevance_score':.1}]}
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'output':data} if native else data)
        monkeypatch.setattr(rerank,'_post',post)
        assert await rerank.rerank('q',['a','b'],top_n=1)==[(1,.9)]
