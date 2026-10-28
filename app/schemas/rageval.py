"""Request schemas for faithfulness review decisions and resolution notes."""
from typing import Literal

from pydantic import BaseModel, Field


class FaithCaseStatusRequest(BaseModel):
    status: Literal["unresolved", "resolved", "dismissed"] = Field(description="Review status")

    resolution: str | None = Field(default=None, max_length=300, description="Resolution notes")
