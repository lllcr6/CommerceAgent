import asyncio

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import settings
from app.core.llm import get_chat_model


class AddInput(BaseModel):
    a: int = Field(description="First operand")
    b: int = Field(description="Second operand")


@tool(args_schema=AddInput)
def add(a: int, b: int) -> int:
    """Add two integers."""

    return a + b


async def main() -> None:
    model = get_chat_model()
    bound = model.bind_tools([add])
    ai = await bound.ainvoke("Use the tool to add 23 and 19.")
    print("content:", repr(ai.content))
    print("tool_calls:", ai.tool_calls)
    if ai.tool_calls and ai.tool_calls[0]["name"] == "add":
        print(f"✅ GO:{settings.chat_model} supports tool calling; selected add, args=", ai.tool_calls[0]["args"])
    else:
        print("FAIL: Expected tool call was not returned. Check the configured model and tool support.")


if __name__ == "__main__":
    asyncio.run(main())
