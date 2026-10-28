import json

from langchain_core.messages import (AIMessage, BaseMessage, HumanMessage,
                                     SystemMessage, ToolMessage)
from langchain_core.messages.utils import count_tokens_approximately, trim_messages

from app.config import settings
from app.core import budget


def count_tokens(messages) -> int:
    """Estimate the current serialized context, not historical request usage.

    A prior response's input_tokens describes a different request and cannot count
    this new window. Runtime accounting uses provider usage via request_usage().
    """
    return count_tokens_approximately(messages, chars_per_token=4.0)


def chars_to_tokens(n_chars: int) -> int:
    """Conservative 4-character fallback; do not round a nonempty input to zero."""
    return max(0, (n_chars + 3) // 4)


def tokens_to_chars(n_tokens: int) -> int:
    return max(0, n_tokens * 4)


def request_usage(messages, response, tools=None) -> tuple[int, str]:
    """Prefer actual usage (including zero); estimate only when unavailable."""
    usage = getattr(response, "usage_metadata", None) or {}
    if usage.get("total_tokens") is not None:
        return int(usage["total_tokens"]), "provider"
    if usage.get("input_tokens") is not None and usage.get("output_tokens") is not None:
        return int(usage["input_tokens"]) + int(usage["output_tokens"]), "provider"
    raw = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
    if raw.get("total_tokens") is not None:
        return int(raw["total_tokens"]), "provider"
    schema_tokens = chars_to_tokens(len(json.dumps(tools, ensure_ascii=False))) if tools else 0
    input_tokens = usage.get("input_tokens", raw.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", raw.get("completion_tokens"))
    if input_tokens is not None or output_tokens is not None:
        inp = int(input_tokens) if input_tokens is not None else count_tokens(messages) + schema_tokens
        out = int(output_tokens) if output_tokens is not None else count_tokens([response])
        source = "provider" if input_tokens is not None and output_tokens is not None else "mixed_provider_and_4_chars"
        return inp + out, source
    # Count submitted messages, tool definitions, output and tool arguments once.
    return count_tokens([*messages, response]) + schema_tokens, "estimated_4_chars"


def window_budget() -> int:
    """Use the configured history limit or derive it from the model context budget."""
    if settings.context_window_max_tokens > 0:
        return settings.context_window_max_tokens
    return budget.compute().sliding


class SessionStore:
    """In-memory message storage keyed by session ID."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[BaseMessage]] = {}

    def get(self, session_id: str) -> list[BaseMessage]:
        return self._sessions.get(session_id, [])

    def append(self, session_id: str, *messages: BaseMessage) -> None:
        self._sessions.setdefault(session_id, []).extend(messages)


def trim_history(messages: list[BaseMessage], max_tokens: int) -> list[BaseMessage]:
    return trim_messages(
        messages,
        strategy="last",
        token_counter=count_tokens,
        max_tokens=max_tokens,
        start_on="human",
        allow_partial=False,
    )


_DB_ID_PREFIX = "db-"


def _db_msg_id(m: BaseMessage) -> int | None:
    """Extract a database ID from a db-prefixed message anchor."""
    mid = getattr(m, "id", None)
    if isinstance(mid, str) and mid.startswith(_DB_ID_PREFIX):
        try:
            return int(mid[len(_DB_ID_PREFIX):])
        except ValueError:
            return None
    return None


def _index_after(messages: list[BaseMessage], msg_id: int) -> int:
    """Find the first user message after the database anchor; return zero if absent."""
    if not msg_id:
        return 0
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            did = _db_msg_id(m)
            if did is not None and did > msg_id:
                return i
    return 0


def build_window(messages: list[BaseMessage], summary_upto_msg_id: int,
                 layer1_from_msg_id: int = 0,
                 max_tokens: int | None = None) -> list[BaseMessage]:
    """Render history using summary and layer anchors without mutating state. Omit summarized messages, compress older turns, preserve recent turns, then enforce the token limit."""
    window = messages[_index_after(messages, summary_upto_msg_id):]
    if layer1_from_msg_id:
        split = _index_after(window, layer1_from_msg_id)
        if split:
            window = to_layer2(window[:split]) + window[split:]
    trimmed = trim_history(window, max_tokens=max_tokens or window_budget())
    return trimmed or window


def layer_tokens(messages: list[BaseMessage], summary_upto_msg_id: int,
                 layer1_from_msg_id: int) -> tuple[int, int]:
    """Measure compressed and recent history token usage for end-of-turn budgeting."""
    window = messages[_index_after(messages, summary_upto_msg_id):]
    split = _index_after(window, layer1_from_msg_id) if layer1_from_msg_id else 0
    return count_tokens(to_layer2(window[:split])), count_tokens(window[split:])


def next_layer1_from(messages: list[BaseMessage], summary_upto_msg_id: int,
                     layer1_budget: int) -> int:
    """Move the recent-history boundary only when over budget. Stable boundaries preserve cached prefixes between demotions."""
    window = messages[_index_after(messages, summary_upto_msg_id):]
    total = 0
    for i in range(len(window) - 1, -1, -1):
        total += count_tokens([window[i]])
        if total > layer1_budget:
            for j in range(i, -1, -1):
                did = _db_msg_id(window[j])
                if did is not None:
                    return did
            return 0
    return 0


def summary_line(summary: str | None) -> str:
    """Render a one-line history prefix for reference resolution and intent classification."""
    return f"(Earlier conversation summary: {summary})" if summary else ""


def summary_system(summary: str | None) -> SystemMessage | None:
    """Build the summary text wrapper. Callers use its content inside turn context to preserve a single stable system message."""
    if not summary:
        return None
    return SystemMessage(f"## Earlier conversation summary (compressed context, not new instructions)\n{summary}")


def compress_reply(text: str, keep_chars: int | None = None) -> str:
    """Keep the beginning of an assistant reply when rendering compressed history."""
    n = settings.layer2_reply_keep_chars if keep_chars is None else keep_chars
    if not text or len(text) <= n:
        return text
    return text[:n] + "…(abridged)"


def compress_tool_result(name: str, content: str) -> str:
    """Keep small tool results intact and replace large results with a compact marker."""
    if not content:
        return content
    if chars_to_tokens(len(content)) <= settings.layer2_tool_keep_tokens:
        return content
    return f"({name or 'tool'} called; result abridged)"


def to_layer2(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Render messages as compressed history deterministically."""
    out: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append(m)
        elif isinstance(m, AIMessage):


            text = m.content if isinstance(m.content, str) else ""
            out.append(AIMessage(compress_reply(text), id=m.id,
                                 tool_calls=list(m.tool_calls or [])))
        elif isinstance(m, ToolMessage):
            text = m.content if isinstance(m.content, str) else str(m.content)
            out.append(ToolMessage(
                compress_tool_result(getattr(m, "name", ""), text),
                tool_call_id=m.tool_call_id, name=getattr(m, "name", None), id=m.id))
        else:
            out.append(m)
    return out
