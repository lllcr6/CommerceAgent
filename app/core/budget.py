"""Allocate model context among fixed prompts, evidence, summaries, output, peak ReAct work, and settled history. Keep peak and settled usage separate."""
from dataclasses import dataclass

from app.config import settings


_KNOWN_WINDOWS: dict[str, int] = {
    "minimax-m3": 1_000_000,
    "minimax-m2": 204_800,
    "deepseek-v4-flash": 1_048_576,
    "deepseek-v4": 1_048_576,
    "deepseek-v3": 131_072,
    "deepseek-chat": 131_072,
    "deepseek-reasoner": 131_072,
    "qwen3": 131_072,
    "qwen-max": 32_768,
    "glm-4": 131_072,
    "kimi-k2": 262_144,
    "moonshot-v1-128k": 131_072,
    "gpt-4.1": 1_047_576,
    "gpt-4o": 128_000,
    "claude-": 200_000,
}
_FALLBACK_WINDOW = 32_768


def lookup_window(model: str) -> tuple[int, bool]:
    """Return the model window and whether it was recognized; unknown models use a conservative default."""

    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    hit = max((k for k in _KNOWN_WINDOWS if name.startswith(k)), key=len, default=None)
    return (_KNOWN_WINDOWS[hit], True) if hit else (_FALLBACK_WINDOW, False)


def resolve_window() -> int:
    """Resolve context capacity from explicit configuration, model lookup, or the conservative default."""
    if settings.model_context_window > 0:
        return settings.model_context_window
    return lookup_window(settings.chat_model)[0]


@dataclass(frozen=True)
class ContextBudget:
    """Token allocation for one request; turns is a count rather than a token quantity."""

    window: int
    fixed: int
    sliding: int
    turns: int
    peak: int
    limited_by: str
    healthy: bool

    @property
    def per_turn(self) -> int:
        """Estimate settled history tokens per turn; peak usage is tracked separately."""
        return history_per_turn()


def summary_tokens() -> int:
    """Reserve space for the configured number of injected summary segments."""
    return settings.summary_inject_segments * settings.summary_tokens_per_segment


def evidence_tokens(top_k: int | None = None) -> int:
    """Reserve evidence space based on the reranked passage count."""
    k = settings.rerank_top_k if top_k is None else top_k
    return k * settings.evidence_tokens_per_chunk


def turn_peak_tokens() -> int:
    """Estimate the peak ReAct turn including intermediate assistant/tool messages. The final answer uses a single fixed output reserve."""
    return settings.max_user_input_tokens + settings.max_agent_steps * (
        settings.tool_result_max_tokens + settings.agent_step_ai_tokens)


def history_per_turn() -> int:
    """Estimate settled history after large tool results are compressed."""
    return (settings.max_user_input_tokens + settings.max_output_tokens
            + settings.max_agent_steps * settings.layer2_tool_keep_tokens)


def compute(window: int | None = None) -> ContextBudget:
    """Compute the context allocation without I/O."""
    w = resolve_window() if window is None else window
    per_turn = history_per_turn()
    peak = turn_peak_tokens()

    fixed = (
        settings.system_prompt_tokens
        + evidence_tokens()
        + summary_tokens()
        + settings.max_output_tokens
        + settings.budget_safety_margin
    )


    room = w - fixed - peak
    if room <= 0:
        return ContextBudget(w, fixed, 0, 0, peak, "window", False)

    by_turns = settings.context_budget_turns * per_turn
    sliding = min(by_turns, room)
    limited_by = "turns" if sliding == by_turns else "window"
    turns = sliding // per_turn
    return ContextBudget(w, fixed, sliding, turns, peak, limited_by, turns >= 1)


def describe(b: ContextBudget) -> str:
    """Format the context allocation for startup diagnostics."""
    return (
        f"window={b.window} fixed={b.fixed} turn_peak={b.peak} history_window={b.sliding} "
        f"turns={b.turns}(history per turn {b.per_turn}) limited_by={b.limited_by} "
        f"healthy={'yes' if b.healthy else 'no'}"
    )
