"""Generate chart notes when reports are saved, never when pages are viewed. Validate every cited number and use dashboard fallbacks on failure."""
import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_CHARS = 130
TIMEOUT = 120.0


_NUM = re.compile(r"(?<![A-Za-z@_.\-\d])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z_])")


KINDS: dict[str, tuple[str, str]] = {
    "rag_mrr": (
        "MRR for Dense, BM25, Hybrid, and Hybrid + Rerank across policy, model, conversational, cross-document, and overall results. Higher values place relevant evidence earlier.",
        "Compare retrieval strategies and identify weak question categories.",
    ),
    "rag_recall": (
        "Recall@5 for four retrieval strategies by question category and overall, including questions requiring multiple documents.",
        "Identify strategies and categories that miss relevant evidence.",
    ),
    "rag_coverage": (
        "Evidence coverage: reference answer points present in the ten retrieved passages.",
        "Assess whether retrieved evidence covers all required answer points.",
    ),
    "rag_answer_coverage": (
        "End-to-end answer coverage using identical generation prompts with different retrieval strategies.",
        "Assess how retrieval quality affects completeness of generated answers.",
    ),
    "cost_by_intent": (
        "Token usage by intent: request count, total tokens, mean tokens per request, and share of usage. Multi-step requests may involve several model calls.",
        "Identify intents to prioritize for prompt or model cost optimization.",
    ),
    "eval_trend": (
        "Recall@5, MRR, faithfulness, and refusal rate in the latest two completed evaluations, including comparable changes.",
        "Check whether knowledge updates warrant reviewing recent approvals.",
    ),
    "confidence_calibration": (
        "Confidence threshold scan: answerable-question pass rate and unsupported-question pass rate at each candidate threshold, with the selected threshold.",
        "Explain the tradeoff between refusing answerable questions and answering unsupported ones.",
    ),
}

_RULES = (
    "Write one concise American-English chart note for a developer dashboard. "
    "Use only numbers present in the supplied data; never invent or recalculate results. "
    f"Use at most {MAX_CHARS} characters and focus on one useful observation or next step. "
    "Use readable labels: Dense, BM25, Hybrid, Hybrid + Rerank; Policy, Model, Conversational, Multi-source. "
    "Distinguish measurements from assumptions and missing values from zero. "
    "Do not claim savings, causality, or statistically significant improvement without evidence. "
    "Return only the note, without a heading, quotes, or Markdown."
)


def _payload_numbers(payload) -> set[str]:
    """Collect accepted numeric forms, including rounding, percentages, and complements of proportions."""
    out: set[str] = set()

    def add(x: float) -> None:
        for s in (f"{x:g}", f"{x:.0f}", f"{x:.1f}", f"{x:.2f}", f"{x:.3f}"):
            out.add(s)

    def walk(node) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            add(float(node))
            add(abs(float(node)) * 100)
            if 0.0 <= float(node) <= 1.0:
                add((1.0 - float(node)) * 100)
                add(1.0 - float(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            for m in _NUM.finditer(node):
                try:
                    add(float(m.group(0).replace(",", "")))
                except ValueError:
                    pass

    walk(payload)
    return {s.rstrip("0").rstrip(".") if "." in s else s for s in out}


def verify(text: str, payload) -> bool:
    """Reject a chart note if any number is unsupported by its data."""
    allowed = _payload_numbers(payload)
    for m in _NUM.finditer(text):
        raw = m.group(0).replace(",", "")
        norm = raw.rstrip("0").rstrip(".") if "." in raw else raw
        if norm not in allowed:
            logger.warning("Chart note rejected: unsupported number %s", raw)
            return False
    return True


def tidy(text: str) -> str:
    """Normalize chart-note spacing and punctuation, including historical notes."""
    text = " ".join(text.split()).strip().strip("「」\"'")
    if not re.search(r"[\u3400-\u9fff]", text):
        text = re.sub(r",(?!\d{3}\b)\s*", ", ", text)
        return text.rstrip(".!? ") + "."
    text = text.replace("，", ",").replace("；", ",").replace(";", ",")
    text = re.sub(r",\s+", ",", text)
    text = re.sub(r"(?<=[一-鿿])(?=[\dA-Za-z])", " ", text)
    text = re.sub(r"(?<=[\dA-Za-z%])(?=[一-鿿])", " ", text)


    text = re.sub(r"(?<=[A-Za-z]{3})(?=\d)", " ", text)
    text = text.rstrip("!!??.、,·… ")
    return text if text.endswith(("。", ")", ")")) else text + "。"


async def generate(kind: str, payload, model=None) -> str | None:
    """Generate a chart note; return None on failure, excess length, or unsupported numbers."""
    what, decision = KINDS[kind]
    if model is None:
        from app.core.llm import get_chat_model
        model = get_chat_model()
    prompt = (f"{_RULES}\n\nChart description: {what}\nDecision to inform: {decision}\n\n"
              f"Data (JSON):\n{json.dumps(payload, ensure_ascii=False)}")
    try:
        resp = await asyncio.wait_for(model.ainvoke(prompt), timeout=TIMEOUT)
    except Exception as e:
        logger.warning("Chart note %s unavailable (%s: %s); using dashboard fallback", kind, type(e).__name__, e)
        return None
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    if re.search(r"[\u3400-\u9fff]", text):
        return None  # Use the metric-based dashboard fallback when a note is not in English.
    text = tidy(text)
    if len(text) <= 1 or len(text) > MAX_CHARS:
        logger.warning("Chart note %s rejected: invalid length %d", kind, len(text))
        return None
    return text if verify(text, payload) else None


async def generate_all(jobs: dict[str, object], model=None) -> dict[str, str]:
    """Generate notes concurrently; omit failures so dashboards use deterministic fallbacks."""
    kinds = list(jobs)
    notes = await asyncio.gather(*(generate(k, jobs[k], model) for k in kinds))
    return {k: n for k, n in zip(kinds, notes) if n}
