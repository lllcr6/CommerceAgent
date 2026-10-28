"""Admin endpoints for starting, polling, and stopping allowlisted background jobs."""
from fastapi import APIRouter, HTTPException

from app.core import jobs

router = APIRouter(prefix="/api/jobs")


def _known(name: str) -> None:
    if name not in jobs.JOBS:
        raise HTTPException(status_code=404, detail=f"Unknown job: {name}")


@router.get("")
async def jobs_list() -> dict:
    return {"jobs": jobs.status_all()}


@router.post("/{name}")
async def job_start(name: str) -> dict:
    _known(name)
    try:
        await jobs.start(name)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Could not start command: {e}") from e
    return jobs.status(name, with_log=True)


@router.get("/{name}")
async def job_status(name: str) -> dict:
    _known(name)
    return jobs.status(name, with_log=True)


@router.post("/{name}/stop")
async def job_stop(name: str) -> dict:
    _known(name)
    try:
        await jobs.stop(name)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return jobs.status(name, with_log=True)
