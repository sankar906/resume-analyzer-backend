from fastapi import APIRouter

from src.api.v1.endpoints import (
    candidates,
    job_description,
    resume_info,
    resume_job_match,
)

api_router = APIRouter()
api_router.include_router(job_description.router, tags=["job-descriptions"])
api_router.include_router(
    resume_info.router, prefix="/resume-info", tags=["resume-info"]
)
api_router.include_router(
    resume_job_match.router, prefix="/resume-job-match", tags=["resume-job-match"]
)
api_router.include_router(
    candidates.router,
    prefix="/candidates",
    tags=["candidates"],
)
