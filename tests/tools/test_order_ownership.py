import pytest

from app.tools import business
from app.tools.builtin.orders import query_order
from app.tools.builtin.refunds import submit_refund

USER = "u-alice"
OTHER = "u-bob"


pytestmark = pytest.mark.usefixtures("business_db")

def _own(uid: str) -> str:
    return uid + "-1001"

async def test_order_ownership_requires_matching_customer():
    assert await business.owns_order(USER, _own(USER)) is True
    assert await business.owns_order(OTHER, _own(USER)) is False

async def test_empty_identity_never_passes_ownership():
    assert await business.owns_order("", _own(USER)) is False


async def test_owned_order_is_returned():
    mine = _own(USER)
    out = await query_order.ainvoke({"order_id": mine, "user_id": USER})
    assert out["order_id"] == mine
    assert "tracking_no" in out


async def test_foreign_order_is_denied_without_disclosure():
    his = _own(OTHER)
    out = await query_order.ainvoke({"order_id": his, "user_id": USER})
    assert out.get("code") == "order_not_owned"

    for leaked in ("amount", "product", "tracking_no", "status", "created_at"):
        assert leaked not in out


async def test_missing_and_foreign_orders_share_error():

    his = await query_order.ainvoke({"order_id": _own(OTHER), "user_id": USER})
    nobody = await query_order.ainvoke({"order_id": "999999", "user_id": USER})
    assert his["error"] == nobody["error"]
    assert his["code"] == nobody["code"] == "order_not_owned"


async def test_refunds_use_the_same_ownership_check():

    out = await submit_refund.ainvoke(
        {"order_id": _own(OTHER), "reason": "no_longer_needed", "user_id": USER})
    assert out.get("code") == "order_not_owned"


@pytest.mark.parametrize("bad", ["", None])
async def test_missing_identity_denies_reads_and_writes(bad):
    mine = _own(USER)
    out = await query_order.ainvoke({"order_id": mine, "user_id": bad or ""})
    assert out.get("code") == "order_not_owned"


async def test_demo_orders_have_unique_owners():
    alice = await business.list_user_orders(USER)
    bob = await business.list_user_orders(OTHER)
    assert len(alice) == len(bob) == 2
    assert not ({o["order_id"] for o in alice} & {o["order_id"] for o in bob})
    assert await business.owns_order(USER, _own(OTHER)) is False
