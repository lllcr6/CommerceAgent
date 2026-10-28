from app.kb.documents import Chunk, build_chunks


def test_policy_maps_heading_and_parent_path():
    md = "# Returns policy\n\n## Shipping fees\n\nOrders over $99 ship free. Other orders pay a $10 shipping fee."
    chunks = build_chunks(md, content_type="policy")
    c = [c for c in chunks if c.questions == "Shipping fees"][0]
    assert c.category == "Returns policy"
    assert c.section_path == "Returns policy / Shipping fees"
    assert "Orders over $99" in c.answer
    assert c.content_type == "policy"
    assert c.is_key_clause == 1


def test_table_section_splits_by_rows_with_header():
    rows = "\n".join(f"| 商品{i} | {i} |" for i in range(1, 15))
    md = f"# 商品价格表\n\n## 价目\n\n| 商品 | 价格 |\n| --- | --- |\n{rows}"
    chunks = build_chunks(md, content_type="manual", table_max_rows=5)
    price = [c for c in chunks if c.questions == "价目"]
    assert len(price) >= 2
    for c in price:
        assert c.answer.startswith("| 商品 | 价格 |")


def test_returns_chunk_dataclass():
    chunks = build_chunks("# A\n\n## B\n\n正文。", content_type="faq")
    assert isinstance(chunks[0], Chunk)
