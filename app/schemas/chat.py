from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.core import memory


class ChatRequest(BaseModel):
    order_id: str | None = Field(default=None, min_length=1, max_length=96)
    user_id: str = Field(default="", description="Customer identifier for conversation ownership")
    message: str = Field(min_length=1, description="Customer message for this turn")
    conversation_id: int | None = Field(
        default=None, description="Existing conversation ID; omit to create one and receive its ID in the done event"
    )

    @field_validator("message")
    @classmethod
    def _within_input_budget(cls, v: str) -> str:
        """Reject oversized customer messages before they can overflow the reserved context budget."""
        limit = settings.max_user_input_tokens
        if memory.count_tokens([("human", v)]) > limit:
            raise ValueError(
                f"This message is too long (approximately {memory.tokens_to_chars(limit)} characters maximum). "
                "Please shorten it or send it in parts.")
        return v
