"""English support regressions: usage provenance, routing, and reference safety."""
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.core import coref, memory, retrieval
from app.core.intent import INTENTS
from app.graph.routing import INTENT_TO_ROUTE, route_by_intent
from app.kb import chunking
from app.kb.evaluation import validate_annotations
from scripts.prepare_english_rag import ROOT, annotate, bind_live, source_chunks


@pytest.mark.parametrize('reported',[0,17,900])
def test_provider_usage_wins_even_for_zero(reported):
    answer=AIMessage('A much longer response than the provider token count.',usage_metadata={
        'input_tokens':reported,'output_tokens':0,'total_tokens':reported})
    assert memory.request_usage([HumanMessage('hello')],answer)==(reported,'provider')


def test_raw_provider_usage_is_not_estimated():
    answer=AIMessage('hello',response_metadata={'token_usage':{'total_tokens':43}})
    assert memory.request_usage([],answer)==(43,'provider')


def test_missing_usage_counts_context_and_output_once():
    msgs=[HumanMessage('Please check order alice-1001.')]
    answer=AIMessage('I can help.',tool_calls=[{'name':'query_order','args':{'order_id':'alice-1001'},'id':'call1'}])
    count,source=memory.request_usage(msgs,answer)
    assert source=='estimated_4_chars'
    assert count==memory.count_tokens([*msgs,answer])
    assert memory.chars_to_tokens(400)==100
    assert memory.chars_to_tokens(1)==1
    assert memory.tokens_to_chars(100)==400


def test_english_routing_keeps_warranty_out_of_refunds():
    assert set(INTENT_TO_ROUTE)==set(INTENTS)
    assert route_by_intent({'intent':'warranty_support'})=='business'
    assert route_by_intent({'intent':'return_refund'})=='refund_flow'
    assert route_by_intent({'intent':'after_sales'})=='business'
    assert route_by_intent({'intent':'shipping'})=='business'


@pytest.mark.asyncio
async def test_ambiguous_two_order_reference_is_not_silently_selected(monkeypatch):
    def forbidden():pytest.fail('Ambiguous order reference must not be assigned by a rewrite')
    monkeypatch.setattr(coref,'get_chat_model',forbidden)
    question='Can I return it?'
    assert await coref.resolve(question,'Order alice-1001 is a fountain. Order alice-2002 is a bed.')==question


@pytest.mark.asyncio
async def test_coreference_rejects_invented_order_identifier(monkeypatch):
    from langchain_core.runnables import RunnableLambda
    monkeypatch.setattr(coref,'get_chat_model',lambda:RunnableLambda(lambda _:AIMessage('Return order bob-9999.')))
    assert await coref.resolve('Can I return it?','Customer: order alice-1001')=='Can I return it?'


def test_noun_conjunction_is_not_a_second_query():
    query='Compare fountains for cats and dogs'
    assert retrieval.split_clauses(query)==[query]
    assert len(retrieval.split_clauses('What is the return window and who pays shipping?'))==2


def test_english_sentence_overlap_preserves_decimal_and_abbreviation():
    text='Use 2.4 GHz Wi-Fi in the U.S. only. Unplug before cleaning.'
    pieces=chunking._split_sentences(text)
    assert ''.join(pieces)==text
    assert '2.4 GHz' in pieces[0] and 'U.S.' in pieces[0]
    out=chunking.apply_sentence_overlap([text,'Check the pump.'],overlap=10)
    assert out[1]=='Unplug before cleaning.Check the pump.'


def test_english_annotation_evidence_and_family_splits_are_consistent():
    chunks=source_chunks()
    cases=json.loads((ROOT/'cases_en.json').read_text())
    rows=annotate(cases,chunks)
    validate_annotations(rows,chunks)
    families={}
    for row in rows:
        families.setdefault(row['family'],set()).add(row['split'])
    assert all(len(splits)==1 for splits in families.values())
    assert {row['split'] for row in rows}=={'dev','heldout'}
    assert all(not r['relevant_chunk_ids'] for r in rows if r['should_refuse'])
    snapshot=json.loads((ROOT/'chunks.json').read_text())
    from scripts.prepare_english_rag import identity
    assert [identity(c) for c in snapshot['chunks']]==[identity(c) for c in chunks]


def test_live_annotation_binding_uses_content_not_assumed_ids():
    chunks=source_chunks()
    live=[dict(c,id=c['id']+500) for c in chunks]
    rebound=bind_live(chunks,live)
    assert rebound[0]['id']==501
    with pytest.raises(ValueError,match='missing or stale'):
        bind_live(chunks,live[:-1])
    with pytest.raises(ValueError,match='duplicate'):
        bind_live(chunks,[*live,live[0]])


def test_partial_actual_usage_keeps_reported_side():
    # A real AIMessage is needed only for estimating its output content.
    response=AIMessage('hello',response_metadata={'token_usage':{'prompt_tokens':11}})
    total,source=memory.request_usage([HumanMessage('x'*4000)],response)
    assert total==11+memory.count_tokens([response])
    assert source=='mixed_provider_and_4_chars'


def test_schema_estimate_is_added_only_when_usage_missing():
    response=AIMessage('hello')
    tools=[{'name':'query_order','description':'Look up an order.'}]
    count,source=memory.request_usage([],response,tools=tools)
    assert count==memory.count_tokens([response])+memory.chars_to_tokens(len(json.dumps(tools)))
    actual=AIMessage('hello',usage_metadata={'input_tokens':1,'output_tokens':1,'total_tokens':2})
    assert memory.request_usage([],actual,tools=tools)==(2,'provider')


def test_legacy_topic_weights_are_disabled_by_default(monkeypatch):
    from fastapi import HTTPException
    from app.core.topic_classifier_status import require_topic_classifier
    from app.config import settings
    from app.config import Settings
    assert Settings.model_fields["topic_classifier_enabled"].default is False
    monkeypatch.setattr(settings, "topic_classifier_enabled", False)
    with pytest.raises(HTTPException) as error:
        require_topic_classifier()
    assert error.value.status_code==503


def test_english_fee_keyword_does_not_match_feeder():
    from app.kb.documents import has_key_terms
    assert not has_key_terms('Feeder features and capacity')
    assert has_key_terms('RETURN label fee')
