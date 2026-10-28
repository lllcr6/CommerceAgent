from typing import Literal

from pydantic import BaseModel


class FeedbackRequest(BaseModel):
    conversation_id: int
    rating: Literal["up", "down"]
    question: str


class FeedbackResponse(BaseModel):
    ok: bool = True
    pooled: bool
