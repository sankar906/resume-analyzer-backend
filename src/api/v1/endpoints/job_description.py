"""Job description endpoints."""

from __future__ import annotations

import logging
import uuid
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder

from src.db.manager import db_manager
from src.schemas.common import BaseResponse
from src.schemas.job_description import (
    JobDescriptionCreate,
    JobDescriptionUpdate,
    build_fn_jobs_args_create,
    build_fn_jobs_args_update,
)

router = APIRouter()

logger = logging.getLogger(__name__)

_FN = "public.fn_job_description"


def _wrap(rows: list[dict]) -> list:
    return jsonable_encoder(rows)


@router.get(
    "/job_description",
    summary="Get job descriptions",
    description="Returns all job descriptions, or a single one when uuid is provided.",
    response_model=BaseResponse,
)
async def get_jobs(
    job_uuid: UUID | None = Query(
        default=None,
        alias="uuid",
        description="Filter by job uuid.",
    ),
) -> BaseResponse:
    try:
        rows = await db_manager.execute_function(_FN, 1, job_uuid)
    except Exception as e:
        logger.exception("get_jobs failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return BaseResponse(
        message="Job descriptions retrieved successfully",
        data=_wrap(rows),
    )


@router.post(
    "/job_description",
    summary="Create job description",
    description="Creates a new job description.",
    response_model=BaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_job(body: JobDescriptionCreate) -> BaseResponse:
    try:
        insert_uuid = uuid.uuid4()
        args = build_fn_jobs_args_create(body, insert_uuid)
        rows = await db_manager.execute_function(_FN, *args)
    except Exception as e:
        logger.exception("create_job failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return BaseResponse(
        message="Job description created successfully",
        data=_wrap(rows),
    )


@router.put(
    "/job_description/{job_uuid}",
    summary="Update job description",
    description="Updates an existing job description. Only provided fields are changed.",
    response_model=BaseResponse,
)
async def update_job(job_uuid: UUID, body: JobDescriptionUpdate) -> BaseResponse:
    try:
        args = build_fn_jobs_args_update(job_uuid, body)
        rows = await db_manager.execute_function(_FN, *args)
    except Exception as e:
        logger.exception("update_job failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    return BaseResponse(
        message="Job description updated successfully",
        data=_wrap(rows),
    )


@router.delete(
    "/job_description/{job_uuid}",
    summary="Delete job description",
    description="Deletes a job description by uuid.",
    response_model=BaseResponse,
)
async def delete_job(job_uuid: UUID) -> BaseResponse:
    try:
        rows = await db_manager.execute_function(_FN, 4, job_uuid)
    except Exception as e:
        logger.exception("delete_job failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    return BaseResponse(
        message="Job description deleted successfully",
        data=_wrap(rows),
    )
