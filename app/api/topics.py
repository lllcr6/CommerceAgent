"""Read-only English topic distributions and paginated classified questions."""
from fastapi import Depends, APIRouter, HTTPException, Query

from app.topic_schema import TOPIC_NAMES
from app.db import repository

from app.topic_schema import require_topic_classifier
router = APIRouter(dependencies=[Depends(require_topic_classifier)])


@router.get("/api/topics/distribution")
async def distribution():
    return await repository.topic_distribution()


@router.get("/api/topics/questions")
async def questions(
    label: str = Query(description="English topic ID from the 17-label schema"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):

    if label not in TOPIC_NAMES:
        raise HTTPException(400, f"Unknown topic: {label}. Expected one of {len(TOPIC_NAMES)} English topic IDs.")
    return await repository.topic_questions(label, page=page, size=size)
