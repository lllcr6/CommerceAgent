import asyncio
from typing import Annotated

from typing_extensions import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt


class S(TypedDict):
    messages: Annotated[list, add_messages]
    picked: str


async def ask_order(state: S):
    picked = interrupt({"type": "select_order",
                        "orders": [{"order_id": "1001"}, {"order_id": "2002"}]})
    return {"picked": picked}


async def confirm(state: S):
    return {"messages": [("ai", f"Selected order: {state['picked']}")]}


async def main():
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        b = StateGraph(S)
        b.add_node("ask_order", ask_order)
        b.add_node("confirm", confirm)
        b.add_edge(START, "ask_order")
        b.add_edge("ask_order", "confirm")
        b.add_edge("confirm", END)
        graph = b.compile(checkpointer=cp)


        config = {"configurable": {"thread_id": "smoke-int-1"}}
        out = await graph.ainvoke({"messages": [("human", "I want to request a refund")]}, config)
        print("A ainvoke keys=", list(out.keys()))
        print("A __interrupt__=", out.get("__interrupt__"))
        if out.get("__interrupt__"):
            print("A first.value=", out["__interrupt__"][0].value)


        out2 = await graph.ainvoke(Command(resume="1001"), config)
        print("B resume picked=", out2.get("picked"), "msgs=", [m.content for m in out2["messages"]])


        config2 = {"configurable": {"thread_id": "smoke-int-2"}}
        print("C astream chunks:")
        async for mode, chunk in graph.astream(
                {"messages": [("human", "I want to request a refund")]}, config2,
                stream_mode=["messages", "updates"]):
            if mode == "updates":
                print("  UPD keys=", list(chunk.keys()), "val=", chunk)

        snap = await graph.aget_state(config2)
        print("C' aget_state .next=", snap.next,
              "interrupts=", getattr(snap, "interrupts", None),
              "tasks_interrupts=", [t.interrupts for t in snap.tasks])

        print("C'' astream resume:")
        async for mode, chunk in graph.astream(
                Command(resume="2002"), config2, stream_mode=["messages", "updates"]):
            print("  ", mode, chunk if mode == "updates"
                  else (chunk[0].content, chunk[1].get("langgraph_node")))


        from langgraph.errors import GraphInterrupt
        try:
            await ask_order({"messages": []})
            print("D no error(unexpected)")
        except GraphInterrupt as e:
            print("D GraphInterrupt first.value=", e.args[0][0].value if e.args else None)
        except RuntimeError as e:
            print("D RuntimeError (interrupt requires graph context):", e)
            print("D: Test missing-order interrupts through the compiled graph. "
                  "Calling the node directly raises RuntimeError rather than GraphInterrupt.")


if __name__ == "__main__":
    asyncio.run(main())
