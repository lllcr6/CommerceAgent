import logging

from pydantic import BaseModel, Field

from app.core import llm
from app.core.llm import get_chat_model
from app.core.prompts import EXPAND_QUERIES_PROMPT, QUERY_REWRITE_PROMPT

logger = logging.getLogger(__name__)


class _Rewrite(BaseModel):
    standard: str = Field(description="Normalized English question")
    expanded: list[str] = Field(default_factory=list, description="English synonyms and related phrases")


class _Expanded(BaseModel):
    queries: list[str] = Field(default_factory=list, description="Exactly three English retrieval queries")


async def understand(query: str) -> dict:
    """Normalize an English question and expand search terms; use the original query on failure."""
    model = llm.structured(_Rewrite)
    try:
        r: _Rewrite = await (QUERY_REWRITE_PROMPT | model).ainvoke({"query": query})
    except Exception:
        logger.warning("Query rewriting failed; using original query=%r", query, exc_info=True)
        return {"standard": query, "expanded": []}
    return {"standard": r.standard or query, "expanded": list(r.expanded or [])}


async def expand_queries(query: str) -> list[str]:
    """Return at most three nonempty search queries. Fall back to the original query on failure."""
    model = llm.structured(_Expanded)
    try:
        r: _Expanded = await (EXPAND_QUERIES_PROMPT | model).ainvoke({"query": query})
        qs = [q.strip() for q in (r.queries or []) if q and q.strip()]
    except Exception:
        qs = []
    return qs[:3] or [query]
