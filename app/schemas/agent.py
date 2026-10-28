from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    user_id: str = Field(default="", description="Customer identifier")
    message: str = Field(min_length=1, description="Customer message for this turn")
    conversation_id: int | None = Field(default=None, description="Existing conversation ID; omit on the first turn")


class ToolCallView(BaseModel):
    id: str
    name: str
    args: dict


class ToolResultView(BaseModel):
    tool_call_id: str
    name: str
    ok: bool
    content: str


class AgentResponse(BaseModel):
    conversation_id: int
    answer: str
    tool_calls: list[ToolCallView]
    tool_results: list[ToolResultView]
    suggested_actions: list = Field(default_factory=list)
    interrupt: dict | None = Field(
        default=None,
        description="Interrupt payload: select_order includes orders; confirm_ticket includes preview; null when absent")
