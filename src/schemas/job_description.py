"""Schemas for job description API (mirrors src.api.v1.endpoints.job_description)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobDetailsBlock(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    department: str | None = None
    level: str | None = None
    location: str | None = None
    employment_type: str | None = None
    remote_allowed: bool | None = None
    status: str
    openings: int


class ReportingBlock(BaseModel):
    hiring_manager: str | None = None
    reporting_to: str | None = None


class ExperienceBlock(BaseModel):
    """Free-text experience requirement; maps to ``job_description.experience``."""

    text: str | None = Field(
        default=None,
        description='e.g. "2 to 4 years in Data Science, Analytics, or related roles."',
    )


class CompensationBlock(BaseModel):
    min_salary: int | None = None
    max_salary: int | None = None


class ContentBlock(BaseModel):
    description: str
    responsibilities: list[str] = []


class JobDescriptionCreate(BaseModel):
    """Request body for creating a job description."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    dossier_id: str | None = None
    created_by: str | None = Field(
        default=None,
        description="User or system creating the record (e.g. recruiter email).",
    )
    job_details: JobDetailsBlock = Field(validation_alias="jobDetails")
    reporting: ReportingBlock
    experience: ExperienceBlock
    compensation: CompensationBlock
    content: ContentBlock
    requirements: dict[str, Any] = Field(
        default_factory=dict,
        description="Stored as JSONB in jobs.requirements",
    )


class JobDetailsPartial(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = None
    department: str | None = None
    level: str | None = None
    location: str | None = None
    employment_type: str | None = None
    remote_allowed: bool | None = None
    status: str | None = None
    openings: int | None = None


class ReportingPartial(BaseModel):
    hiring_manager: str | None = None
    reporting_to: str | None = None


class ExperiencePartial(BaseModel):
    text: str | None = None


class CompensationPartial(BaseModel):
    min_salary: int | None = None
    max_salary: int | None = None


class ContentPartial(BaseModel):
    description: str | None = None
    responsibilities: list[str] | None = None


class JobDescriptionUpdate(BaseModel):
    """Request body for updating a job description. All fields are optional."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    dossier_id: str | None = None
    updated_by: str | None = Field(
        default=None,
        description="User or system performing the update (e.g. recruiter email).",
    )
    job_details: JobDetailsPartial | None = Field(
        default=None,
        validation_alias="jobDetails",
    )
    reporting: ReportingPartial | None = None
    experience: ExperiencePartial | None = None
    compensation: CompensationPartial | None = None
    content: ContentPartial | None = None
    requirements: dict[str, Any] | None = None


def responsibilities_to_text(items: list[str] | None) -> str | None:
    if items is None:
        return None
    return "\n".join(items)


def build_fn_jobs_args_create(
    body: JobDescriptionCreate,
    insert_uuid: UUID,
) -> tuple[Any, ...]:
    jd = body.job_details
    rep = body.reporting
    exp = body.experience
    comp = body.compensation
    cont = body.content
    return (
        2,
        insert_uuid,
        jd.title,
        jd.department,
        jd.location,
        cont.description,
        body.requirements if body.requirements else None,
        responsibilities_to_text(cont.responsibilities),
        jd.status,
        exp.text,
        comp.min_salary,
        comp.max_salary,
        jd.employment_type,
        jd.remote_allowed,
        rep.hiring_manager,
        jd.openings,
        body.dossier_id,
        jd.level,
        rep.reporting_to,
    )


def build_fn_jobs_args_update(
    job_uuid: UUID, body: JobDescriptionUpdate
) -> tuple[Any, ...]:
    jd = body.job_details
    rep = body.reporting
    exp = body.experience
    comp = body.compensation
    cont = body.content

    return (
        3,
        job_uuid,
        jd.title if jd else None,
        jd.department if jd else None,
        jd.location if jd else None,
        cont.description if cont else None,
        body.requirements,
        responsibilities_to_text(cont.responsibilities) if cont is not None else None,
        jd.status if jd else None,
        exp.text if exp else None,
        comp.min_salary if comp else None,
        comp.max_salary if comp else None,
        jd.employment_type if jd else None,
        jd.remote_allowed if jd else None,
        rep.hiring_manager if rep else None,
        jd.openings if jd else None,
        body.dossier_id,
        jd.level if jd else None,
        rep.reporting_to if rep else None,
    )
