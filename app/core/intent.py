from typing import Literal

from pydantic import BaseModel, Field

from app.config import settings
from app.core import llm
from app.core.prompts import INTENT_CLASSIFY_PROMPT

INTENTS = ("shipping", "order_status", "product_policy", "return_refund", "warranty_support", "complaint", "human_support", "chitchat", "other")

class _Intent(BaseModel):
    intent: Literal["shipping", "order_status", "product_policy", "return_refund", "warranty_support", "complaint", "human_support", "chitchat", "other"] = Field(description="One stable intent ID")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Classification confidence from 0 to 1")


async def classify(query: str, history: str = "") -> dict:
    """Return one of nine English intent IDs and its confidence. Provider failures propagate to the API instead of becoming an other intent."""
    model = llm.structured(_Intent, slot="intent")
    r: _Intent = await (INTENT_CLASSIFY_PROMPT | model).ainvoke(
        {"query": query, "history": history or "(none)"})
    intent = r.intent if r.intent in INTENTS else "other"
    return {"intent": intent, "confidence": float(r.confidence)}
