import pytest

from app.core import read_notes

PAYLOAD = {
    "rows": [{"intent": "商品咨询", "count": 3, "tokens": 8821, "avg_tokens": 2940, "share": 0.47},
             {"intent": "物流", "count": 1, "tokens": 7942, "avg_tokens": 7942, "share": 0.42}],
    "total_tokens": 18720,
}


class _Stub:


    def __init__(self, text, boom=False):
        self.text, self.boom, self.calls = text, boom, 0

    async def ainvoke(self, prompt):
        self.calls += 1
        if self.boom:
            raise RuntimeError("上游没起")
        return type("R", (), {"content": self.text})()


def test_numbers_in_the_data_pass():

    assert read_notes.verify("商品咨询占 47%,单均 2,940 token", PAYLOAD)
    assert read_notes.verify("总账 18720 token,物流单均 7942", PAYLOAD)


def test_ratio_complement_passes():

    assert read_notes.verify("代价是 15% 的可答被误拦", {"pass_rate": 0.85})


def test_numbers_inside_identifiers_are_not_claims():

    assert read_notes.verify("可答的 p25 已经到 0.47,Recall@10 那栏别看了", PAYLOAD)
    assert read_notes.verify("重排用的是 bge-reranker-v2-m3,单均 7942 最高", PAYLOAD)


def test_invented_number_is_rejected():

    assert read_notes.verify("商品咨询占 61%", PAYLOAD) is False


async def test_generate_returns_verified_text():
    stub = _Stub("Products account for 47% of tokens")
    note = await read_notes.generate("cost_by_intent", PAYLOAD, model=stub)
    assert note == "Products account for 47% of tokens."
    assert stub.calls == 1


@pytest.mark.parametrize("raw,want", [

    ("商品咨询占 47%，先给它瘦 prompt；物流那路再说", "商品咨询占 47%,先给它瘦 prompt,物流那路再说。"),
    ("占比 0.47, 单均 2940 最高", "占比 0.47,单均 2940 最高。"),

    ("口语类才0.85,答题要点漏了", "口语类才 0.85,答题要点漏了。"),
    ("0.85的通过率够用", "0.85 的通过率够用。"),

    ("要点覆盖全。!", "要点覆盖全。"),
    ("先看这条线", "先看这条线。"),

    ("商品咨询总token8821,先瘦prompt", "商品咨询总 token 8821,先瘦 prompt。"),

    ("可答 p25 到 0.47,重排用 bge-m3,Recall@10 别看", "可答 p25 到 0.47,重排用 bge-m3,Recall@10 别看。"),
])
def test_tidy_matches_the_pages_own_typography(raw, want):

    assert read_notes.tidy(raw) == want


async def test_generated_note_comes_back_tidied():
    stub = _Stub("Products account for 47%,review their prompt")
    assert await read_notes.generate("cost_by_intent", PAYLOAD, model=stub) \
        == "Products account for 47%, review their prompt."


async def test_generate_drops_hallucinated_note():
    stub = _Stub("商品咨询占 61%,已经烧掉 99,999 token")
    assert await read_notes.generate("cost_by_intent", PAYLOAD, model=stub) is None


async def test_generate_drops_overlong_note():

    stub = _Stub("商品咨询占 47%。" * 40)
    assert await read_notes.generate("cost_by_intent", PAYLOAD, model=stub) is None


async def test_upstream_down_is_not_an_error():

    stub = _Stub("", boom=True)
    assert await read_notes.generate("cost_by_intent", PAYLOAD, model=stub) is None


async def test_generate_all_keeps_only_the_good_ones():
    class _PerKind:
        async def ainvoke(self, prompt):
            text = "Shipping averages 7942 tokens" if "Token usage by intent" in prompt else "Invented 12345 requests"
            return type("R", (), {"content": text})()

    notes = await read_notes.generate_all(
        {"cost_by_intent": PAYLOAD, "rag_mrr": PAYLOAD}, model=_PerKind())
    assert list(notes) == ["cost_by_intent"]


@pytest.mark.parametrize("kind", sorted(read_notes.KINDS))
def test_every_kind_declares_what_and_why(kind):

    what, decision = read_notes.KINDS[kind]
    assert len(what) > 10 and len(decision) > 8


async def test_generation_rejects_legacy_language_note():
    assert await read_notes.generate("cost_by_intent", PAYLOAD, model=_Stub("商品咨询占 47%")) is None


def test_english_typography_preserves_thousands_and_identifiers():
    assert read_notes.tidy('Shipping averages 7,942 tokens,review traces') == 'Shipping averages 7,942 tokens, review traces.'
    assert read_notes.tidy('BM25 and Recall@10 improve') == 'BM25 and Recall@10 improve.'
