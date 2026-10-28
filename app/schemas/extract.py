from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1, description="Original customer support request")


class RequestType(str, Enum):
    REFUND = "refund"
    EXCHANGE = "exchange"
    REPAIR = "repair"
    COMPLAINT = "complaint"
    OTHER = "other"


class AfterSalesTicket(BaseModel):
    """Structured information extracted from a customer support request."""

    order_id: str | None = Field(
        default=None, description="Order ID copied from the request, or null when absent; never invent one"
    )
    request_type: RequestType = Field(description="Customer request type")
    expected_solution: str = Field(description="Customer requested resolution, summarized in one sentence")

    @field_validator("order_id", mode="before")
    @classmethod
    def _normalize_missing_order_id(cls, v: object) -> object:

        if isinstance(v, str) and v.strip().lower() in {"", "null", "none", "n/a"}:
            return None
        return v
