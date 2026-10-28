import pytest
pytestmark = pytest.mark.usefixtures("business_db")
from app.tools import business
from app.tools.builtin.orders import query_order, query_product

USER = "u-mock"
MINE = "u-mock-1001"


async def test_query_order_deterministic_and_shaped():

    r1 = await query_order.ainvoke({"order_id": MINE, "user_id": USER})
    r2 = await query_order.ainvoke({"order_id": MINE, "user_id": USER})
    assert r1 == r2
    assert r1["order_id"] == MINE
    assert r1["status"] in {"awaiting_payment", "paid", "shipped", "delivered"}
    assert r1["tracking_no"].startswith("DEMO-US-")


async def test_query_product_names_and_determinism():
    assert query_order.name == "query_order"
    assert query_product.name == "query_product"
    p1 = await query_product.ainvoke({"product_name": "MH-LP100"})
    p2 = await query_product.ainvoke({"product_name": "MH-LP100"})
    assert p1 == p2
    assert p1["product_name"] == "Self-Cleaning Litter Box Pro" and "price" in p1
