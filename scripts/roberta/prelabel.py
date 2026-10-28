import asyncio

from pydantic import BaseModel, Field

from app.core.llm import get_chat_model
from app.core.taxonomy import LABEL2ID, terminology_table


class _Labeled(BaseModel):
    labels: list[str] = Field(description="Unique stable English topic IDs from the schema")


PRELABEL_PROMPT = """Label this English U.S. pet-supply support message using the topic IDs below.
{terminology}

Include only explicitly expressed requests. A size complaint does not imply a return.
Separate shipping fees from delivery tracking, repairs from returns, and coupons from
post-purchase price adjustments. Understand informal English and typos without
inventing requests. Use other only when no specific topic applies; never combine it
with another label. Return unique stable topic IDs, not display names.

Customer message: {text}"""


async def prelabel_one(text: str) -> list[str]:
    model = get_chat_model().with_structured_output(_Labeled)
    try:
        r: _Labeled = await model.ainvoke(
            PRELABEL_PROMPT.format(terminology=terminology_table(), text=text))
    except Exception as e:

        print(f"[prelabel] Labeling failed; using other: {text[:30]}… ({type(e).__name__}: {e})")
        return ["other"]
    labels = [lb for lb in r.labels if lb in LABEL2ID]
    return [label for label in dict.fromkeys(labels) if label != "other"] or ["other"]


async def prelabel_batch(texts: list[str], concurrency: int = 8) -> list[list[str]]:
    sem = asyncio.Semaphore(concurrency)

    async def one(t: str) -> list[str]:
        async with sem:
            return await prelabel_one(t)

    return list(await asyncio.gather(*[one(t) for t in texts]))
