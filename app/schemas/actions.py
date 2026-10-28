from typing import Literal

from pydantic import BaseModel, Field


class CreateTicketRequest(BaseModel):
    order_id: str | None = Field(default=None, min_length=1, max_length=96)
    conversation_id: int
    description: str = Field(min_length=1)
    ticket_type: Literal["after_sales", "complaint", "question"]


class CreateTicketResponse(BaseModel):
    ticket_no: str
    status: str = "pending"


class CreateRefundRequest(BaseModel):
    conversation_id: int
    order_id: str = Field(min_length=1)
    reason: Literal["change_of_mind", "defective_item", "wrong_item", "no_longer_needed", "other"]



class CreateRefundResponse(BaseModel):
    ticket_no: str
    status: str = "Refund request submitted"


class ResumeRequest(BaseModel):
    conversation_id: int
    order_id: str | None = Field(default=None, min_length=1)
    confirmed: bool | None = None
