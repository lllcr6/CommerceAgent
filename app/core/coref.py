import re

from app.core.llm import get_chat_model
from app.core.prompts import COREF_REWRITE_PROMPT


async def resolve(query: str, history: str = "") -> str:
    """Resolve references using recent history; return the original query on failure."""
    # Multiple prior orders plus a bare demonstrative is not a safe selection.
    order_ids = set(re.findall(r"\b[A-Za-z][A-Za-z0-9_.-]*-\d{4,}\b", history))
    if len(order_ids) > 1 and re.search(r"\b(?:it|this one|that one|the other one|this order|that order)\b", query, re.I) and not any(oid in query for oid in order_ids):
        return query
    try:
        model = get_chat_model()
        r = await (COREF_REWRITE_PROMPT | model).ainvoke(
            {"query": query, "history": history or "(none)"})
        text = (r.content if isinstance(r.content, str) else "").strip()
    except Exception:
        return query
    ids = re.compile(r"\b(?:MH-[A-Za-z]{1,4}\d{1,4}|[A-Za-z][A-Za-z0-9_.-]*-\d{4,})\b")
    allowed = set(ids.findall(query + " " + history))
    if any(value not in allowed for value in ids.findall(text)):
        return query
    return text or query
