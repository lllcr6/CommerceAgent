"""Validate MH product model numbers against exact evidence strings before returning an answer."""
import re

MODEL_RE = re.compile(r"MH-[A-Za-z]{1,4}\d{1,4}")


def models_in(text: str) -> list[str]:
    """Return unique product model numbers in order of appearance."""
    seen: dict[str, None] = {}
    for m in MODEL_RE.findall(text or ""):
        seen.setdefault(m, None)
    return list(seen)


def unsupported_models(answer: str, evidence: str) -> list[str]:
    """Return answer model numbers absent from this turn's evidence."""
    allowed = set(models_in(evidence))
    return [m for m in models_in(answer) if m not in allowed]


def repair_hint(bad: list[str]) -> str:
    """Request correction of unsupported model numbers without guessing replacements."""
    return (
        "The following model numbers in your previous answer are absent from the evidence: " + "、".join(bad) + ". Rewrite the answer: copy model numbers exactly from the evidence. Omit unsupported or uncertain model numbers. Preserve the remaining content and citation numbers."
    )
