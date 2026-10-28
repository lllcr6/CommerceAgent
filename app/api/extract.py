import logging

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.runnables import Runnable

from app.core.llm import get_chat_model
from app.core.prompts import EXTRACT_PROMPT
from app.schemas.extract import AfterSalesTicket, ExtractRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def get_extractor() -> Runnable:
    model = get_chat_model()
    return EXTRACT_PROMPT | model.with_structured_output(AfterSalesTicket)


@router.post("/api/extract", response_model=AfterSalesTicket)
async def extract(
    req: ExtractRequest, extractor: Runnable = Depends(get_extractor)
) -> AfterSalesTicket:
    try:
        return await extractor.ainvoke({"text": req.text})
    except Exception as exc:
        logger.exception("Structured extraction failed")
        raise HTTPException(status_code=502, detail="The model service is temporarily unavailable. Please try again shortly.") from exc
