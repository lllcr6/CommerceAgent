from scripts.roberta.corpus_lib import dedupe, desensitize, split_dataset


def test_desensitize_masks_sensitive_keeps_model_no():
    assert desensitize("Call 202-555-0142 please") == "Call [phone] please"
    assert desensitize("Order 202601180001234567 is late") == "Order [reference] is late"
    assert desensitize("Email alex@example.com") == "Email [email]"
    assert "MH-LP100" in desensitize("How do I clean MH-LP100?")


def test_dedupe_keeps_first():
    out = dedupe([{"text": "a", "origin": "pool"}, {"text": "a", "origin": "simulated"},
                  {"text": "b", "origin": "pool"}])
    assert [s["text"] for s in out] == ["a", "b"]
    assert out[0]["origin"] == "pool"


def _make_samples():
    samples = []
    for cls, n in (("returns_refunds", 40), ("delivery_tracking", 40), ("size_fit", 30)):
        samples += [{"text": f"{cls} question {i}", "labels": [cls]} for i in range(n)]
    samples += [{"text": f"Multiple requests {i}", "labels": ["size_fit", "returns_refunds"]} for i in range(12)]
    samples += [{"text": f"Small combination {i}", "labels": ["delivery_tracking", "returns_refunds"]} for i in range(3)]
    return samples


def test_split_ratio_and_no_leakage():
    train, val, test = split_dataset(_make_samples())
    total = len(train) + len(val) + len(test)
    assert total == 125
    assert 0.72 <= len(train) / total <= 0.88
    texts = [s["text"] for s in train + val + test]
    assert len(texts) == len(set(texts))


def test_split_every_class_in_every_split():
    train, val, test = split_dataset(_make_samples())
    for split in (train, val, test):
        found = {lb for s in split for lb in s["labels"]}
        assert {"returns_refunds", "delivery_tracking", "size_fit"} <= found


def test_split_deterministic():
    a = split_dataset(_make_samples(), seed=42)
    b = split_dataset(_make_samples(), seed=42)
    assert a == b
