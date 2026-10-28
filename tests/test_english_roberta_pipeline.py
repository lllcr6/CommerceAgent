"""Offline integration: random tiny RoBERTa, temporary artifacts, no model API calls."""
import json
from types import SimpleNamespace
import numpy as np
import pytest
from app.topic_schema import (ID2LABEL, LABEL2ID, NUM_CLASSES, OTHER_ID, SCHEMA_VERSION,
                              SCHEMA_SHA256, TOPIC_NAMES)
from scripts.roberta.inference_lib import POLICY, apply_threshold, scan_thresholds
from scripts.roberta.model_contract import encode, seal_artifact, validate_artifact


def test_other_exclusive_and_shared_threshold_selection():
    probs = np.full((3, NUM_CLASSES), .1)
    probs[0, 0] = .7; probs[0, OTHER_ID] = .9
    probs[1, OTHER_ID] = .8
    probs[2, 1] = .2
    pred = apply_threshold(probs, .5, OTHER_ID)
    assert pred.sum(axis=1).tolist() == [1, 1, 1]
    assert pred[0, 0] and not pred[0, OTHER_ID]
    assert pred[1, OTHER_ID] and pred[2, 1]
    best, scan = scan_thresholds(probs, pred, OTHER_ID)
    assert best['threshold'] == .5 and len(scan) == 9
    with pytest.raises(ValueError): apply_threshold(np.array([[np.nan]]), .5)


@pytest.fixture
def tiny_model(tmp_path):
    pytest.importorskip('transformers')
    from tokenizers import Tokenizer, models, trainers, pre_tokenizers, processors, decoders
    from transformers import PreTrainedTokenizerFast, RobertaConfig, RobertaForSequenceClassification
    tok = Tokenizer(models.BPE(unk_token='<unk>'))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    tok.train_from_iterator(['Where is my order?', 'Can I return this dog harness?', 'cat food'] * 2,
        trainers.BpeTrainer(vocab_size=300, special_tokens=['<s>', '<pad>', '</s>', '<unk>', '<mask>'],
                            initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    tok.post_processor = processors.RobertaProcessing(('</s>', 2), ('<s>', 0), trim_offsets=True, add_prefix_space=False)
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=tok, bos_token='<s>', eos_token='</s>',
        unk_token='<unk>', pad_token='<pad>', mask_token='<mask>', model_input_names=['input_ids','attention_mask'])
    config = RobertaConfig(vocab_size=len(tokenizer), hidden_size=16, num_hidden_layers=1,
        num_attention_heads=2, intermediate_size=32, max_position_embeddings=130, pad_token_id=1,
        bos_token_id=0, eos_token_id=2, type_vocab_size=1, num_labels=NUM_CLASSES,
        id2label=ID2LABEL, label2id=LABEL2ID, problem_type='multi_label_classification',
        hidden_dropout_prob=0., attention_probs_dropout_prob=0.)
    model = RobertaForSequenceClassification(config)
    directory = tmp_path / 'model'; directory.mkdir()
    model.save_pretrained(directory); tokenizer.save_pretrained(directory)
    (directory / 'threshold.json').write_text(json.dumps({'threshold': .5, 'selected_on': 'val'}))
    seal_artifact(directory, dict(language='en-US', schema_version=SCHEMA_VERSION,
        labels_sha256=SCHEMA_SHA256, labels=list(TOPIC_NAMES), decision_policy=POLICY,
        max_length=64, dataset_manifest_sha256='temporary-fixture', dataset_status='test_fixture'))
    return directory, tokenizer, model


def test_encode_and_trainer_step(tiny_model, tmp_path):
    from transformers import Trainer, TrainingArguments, default_data_collator
    from scripts.roberta.train import BestInMemory, compute_metrics
    directory, tokenizer, model = tiny_model
    rows = [{'text': 'Where is my order?', 'labels':['delivery_tracking']},
            {'text': 'Can I return this dog harness?', 'labels':['returns_refunds','size_fit']}]
    features = encode(rows, tokenizer, 64)
    assert set(features[0]) == {'input_ids','attention_mask','labels'}
    assert features[0]['input_ids'][-1] == 1
    assert len(features[0]['labels']) == 17
    callback = BestInMemory(model, patience=2)
    trainer = Trainer(model=model, args=TrainingArguments(output_dir=str(tmp_path/'logs'),
        use_cpu=True, max_steps=1, per_device_train_batch_size=2, per_device_eval_batch_size=2,
        eval_strategy='steps', eval_steps=1, save_strategy='no', report_to='none', disable_tqdm=True),
        train_dataset=features, eval_dataset=features, data_collator=default_data_collator,
        compute_metrics=compute_metrics, callbacks=[callback])
    trainer.train()
    assert callback.best_state is not None and callback.best_metric >= 0
    # Two unimproved evaluations stop training without requiring disk checkpoints.
    control = SimpleNamespace(should_training_stop=False)
    for _ in range(2): callback.on_evaluate(None, None, control, {'eval_micro_f1':callback.best_metric})
    assert control.should_training_stop


def test_onnx_serving_parity_and_artifact_guard(tiny_model, tmp_path):
    pytest.importorskip('onnxruntime')
    from scripts.roberta.export_onnx import export_model
    from scripts.roberta.serve import Runtime, create_app
    from fastapi.testclient import TestClient
    directory, tokenizer, model = tiny_model
    output = tmp_path / 'onnx'
    texts = ['cat', 'Where is my order?', 'Can I return this dog harness?', 'food ' * 100]
    report = export_model(directory, output, texts, batch_size=2)
    assert report['passed'] and report['parity_split'] == 'val'
    runtime = Runtime(output)
    assert runtime.manifest['pad_id'] == 1 and runtime.manifest['pad_token'] == '<pad>'
    assert runtime.classify([]) == []
    import torch
    from scripts.roberta.inference_lib import sigmoid
    for batch in [texts[:1], texts[1:3], texts[3:]]:
        enc = tokenizer(batch, padding=True, truncation=True, max_length=64, return_tensors='pt')
        model.eval()
        with torch.no_grad(): expected = sigmoid(model(**enc).logits.numpy())
        actual = runtime.classify(batch)
        np.testing.assert_allclose(np.array([list(r['scores'].values()) for r in actual]), expected, atol=1e-3)
        assert all(set(r['labels']) <= set(TOPIC_NAMES) for r in actual)
    with TestClient(create_app(output)) as client:
        assert client.get('/healthz').json()['schema_version'] == SCHEMA_VERSION
        assert client.post('/classify', json={'texts':[]}).json()['results'] == []
    (output / 'threshold.json').write_text('{"threshold":0.1}')
    with pytest.raises(ValueError, match='changed'): validate_artifact(output)


def test_training_fails_before_model_download_when_audit_fails(monkeypatch):
    pytest.importorskip('sklearn')
    pytest.importorskip('transformers')
    from scripts.roberta import train, validate_dataset
    def invalid(): raise AssertionError('Frozen release changed')
    def download(*args, **kwargs): raise AssertionError('Unexpected pretrained model download')
    monkeypatch.setattr(validate_dataset, 'validate', invalid)
    monkeypatch.setattr(train.AutoTokenizer, 'from_pretrained', download)
    with pytest.raises(AssertionError, match='Frozen release changed'):
        train.main(SimpleNamespace(epochs=1, batch_size=1, seed=42, local_files_only=True))


async def test_batch_refuses_wrong_runtime_without_writes(monkeypatch):
    from scripts.roberta import classify_pool
    from app.config import settings
    monkeypatch.setattr(settings, 'topic_classifier_enabled', True)
    writes = []
    async def pending(**kwargs): return [{'question_id':1,'text':'Where is my parcel?'}]
    async def save(rows): writes.extend(rows); return len(rows)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'ok':True, 'language':'zh-CN'}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url): return Response()
        async def post(self, *args, **kwargs): pytest.fail('Wrong runtime must be refused before classification')
    monkeypatch.setattr(classify_pool.repository,'list_unclassified_questions',pending)
    monkeypatch.setattr(classify_pool.repository,'insert_topic_classifications',save)
    monkeypatch.setattr(classify_pool.httpx,'AsyncClient',Client)
    with pytest.raises(ValueError, match='verified English'):
        await classify_pool.main(1, True)
    assert not writes


async def test_dataset_visible_while_classifier_disabled_and_old_labels_refused(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.config import settings
    from app.api import acceptance, topics
    monkeypatch.setattr(settings, 'topic_classifier_enabled', False)
    app = FastAPI(); app.include_router(acceptance.router); app.include_router(topics.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        data = await client.get('/api/acceptance/data')
        assert data.status_code == 200
        payload = data.json()
        assert payload['topic_names'] == list(TOPIC_NAMES)
        assert payload['dataset']['clean']
        assert (await client.post('/api/acceptance/classify',json={'text':'Hello'})).status_code == 503
        monkeypatch.setattr(settings, 'topic_classifier_enabled', True)
        assert (await client.get('/api/topics/questions',params={'label':'退换货'})).status_code == 400
