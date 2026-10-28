from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool
from pydantic import Field

from app.tools import registry
from app.demo_catalog import find_products
from app.tools.business import order_snapshot, owns_order


NOT_OWNED = {"error": "No matching order was found for your account.", "code": "order_not_owned"}


@tool
async def query_order(
    order_id: Annotated[str, Field(description="Exact order number, for example alice-1001")],
    user_id: Annotated[str, InjectedToolArg],
) -> dict:
    """Look up a customer-owned order: state, amount, product, date, and tracking_no.
    To retrieve carrier events, pass the returned tracking_no to query_logistics.
    User identity is injected by the system; do not supply it.
    """
    if not await owns_order(user_id, order_id):
        return dict(NOT_OWNED)
    return await order_snapshot(order_id)


@tool
async def query_product(
    product_name: Annotated[str, Field(description="Product name, model ID, or keywords, e.g. dog harness or MH-LP100")],
) -> dict:
    """Look up documented demo products by name, model, or category keywords.
    Multiple matches are candidates to compare or clarify. Null price or stock
    means unknown; do not invent it. Read the explicit currency before quoting.
    Unknown products return product_not_found. These are simulated records.
    """
    items=[p.view() for p in find_products(product_name)]
    if not items:
        return {'error':'That product is not in the catalog. Check its name or model.','code':'product_not_found'}
    if len(items)==1:
        return items[0]
    return {'items':items,'is_demo':True,'message':'Several models match. Compare their documented features or clarify the model.'}


registry.register(registry.spec_from_langchain_tool(
    query_order, source="builtin", inject_user_id=True))
registry.register(registry.spec_from_langchain_tool(query_product, source="builtin"))
