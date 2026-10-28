import logging

from pydantic import BaseModel, Field

from app.core import llm
from app.core.llm import get_chat_model
from app.core.prompts import SELF_CHECK_PROMPT

logger = logging.getLogger(__name__)


class _Check(BaseModel):
    useful: bool = Field(description="Whether the evidence is sufficient to answer")
    reason: str = Field(default="", description="Reason for the judgment")


def _chain():
    return SELF_CHECK_PROMPT | llm.structured(_Check)


async def check_sufficient(query: str, evidence_texts: list[str]) -> dict:
    """Check evidence before generation. Fail closed on model errors and route unsupported questions to review."""
    evidence = "\n".join(f"[{i+1}] {t}" for i, t in enumerate(evidence_texts)) or "(no evidence)"
    try:
        r: _Check = await _chain().ainvoke({"query": query, "evidence": evidence})
    except Exception:
        logger.warning("Evidence self-check failed; treating evidence as insufficient: query=%r", query, exc_info=True)
        return {"useful": False, "reason": "Evidence self-check failed"}
    return {"useful": bool(r.useful), "reason": r.reason or ""}
