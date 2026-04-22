"""Pydantic models for resume extraction and evaluation."""

from datetime import date
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --------------------------------------------------
# Extraction models
# --------------------------------------------------


class Experience(BaseModel):
    job_title: str = Field(description="Job title or role")
    company: str = Field(description="Company name")
    location: Optional[str] = Field(default=None, description="Job location")
    employment_type: Optional[str] = Field(
        default=None, description="e.g. Full-time, Intern, Contract"
    )
    start_date: Optional[date] = Field(
        default=None, description="Start date YYYY-MM-DD. Null if not mentioned."
    )
    end_date: Optional[date] = Field(
        default=None, description="End date YYYY-MM-DD. Null if currently working."
    )
    responsibilities: List[str] = Field(
        description="Key responsibilities and achievements"
    )


class Education(BaseModel):
    degree: str = Field(description="Degree obtained e.g. B.Tech, MSc")
    field_of_study: Optional[str] = Field(default=None, description="Field of study")
    institution: str = Field(description="Name of institution or university")
    institution_location: Optional[str] = Field(
        default=None, description="Location of the institution"
    )
    graduation_year: Optional[int] = Field(
        default=None, description="Year of graduation YYYY"
    )
    gpa: Optional[float] = Field(
        default=None, description="GPA or percentage if mentioned"
    )


class Project(BaseModel):
    name: str = Field(description="Project name")
    description: Optional[str] = Field(default=None, description="Brief description")
    technologies: Optional[List[str]] = Field(
        default=None, description="Technologies used"
    )


class ResumeInfo(BaseModel):
    name: str = Field(description="Full name of the candidate")
    email: Optional[str] = Field(
        default=None, description="Email address. Null if not present."
    )
    phone: Optional[str] = Field(
        default=None, description="Phone number with country code if available"
    )
    location: Optional[str] = Field(
        default=None, description="Current location city country"
    )
    linkedin: Optional[str] = Field(
        default=None, description="LinkedIn profile URL if available"
    )
    summary: Optional[str] = Field(
        default=None, description="Professional summary or objective"
    )
    total_experience_years: Optional[float] = Field(
        default=None,
        description="Total years of professional experience. Null if unclear.",
    )
    current_role: Optional[str] = Field(
        default=None, description="Current job title if identifiable"
    )
    skills: List[str] = Field(
        description="List of technical and soft skills. No duplicates."
    )
    experience: List[Experience] = Field(description="Professional work experiences")
    education: List[Education] = Field(description="Educational background")
    projects: Optional[List[Project]] = Field(
        default=None,
        description="Projects if `projects` section is present, Do not put here from experince section ",
    )
    certifications: Optional[List[str]] = Field(
        default=None, description="Certifications e.g. AWS Certified Developer"
    )
    languages: Optional[List[str]] = Field(default=None, description="Languages spoken")


# --------------------------------------------------
# Evaluation models
# --------------------------------------------------


class EvaluationSection(BaseModel):
    rating: int = Field(ge=0, le=100, description="Score from 0 to 100")
    reason: str = Field(
        description="Evidence from the resume. If missing, write 'No evidence found.'"
    )


class EvaluationOutput(BaseModel):
    knowledge_areas: EvaluationSection
    technical_skills: EvaluationSection
    experience: EvaluationSection
    certifications: Optional[EvaluationSection] = None
    final_rating: int = Field(ge=0, le=100, description="Overall score from 0 to 100")
    final_verdict: Literal["Strong Hire", "Average", "Reject"]
    final_justification: str = Field(
        description="One sentence justification for the final verdict"
    )


# --------------------------------------------------
# Resume–job match (PDF + prompt → Gemini; persisted as scalar columns)
# --------------------------------------------------


class ResumeJobMatchOutput(BaseModel):
    """Structured output when matching a resume PDF against one or more job descriptions."""

    name: Optional[str] = Field(
        default=None, description="Full name as read from the resume document."
    )
    email: Optional[str] = Field(default=None, description="Email if present.")
    phone: Optional[str] = Field(default=None, description="Phone if present.")
    currentrole: Optional[str] = Field(
        default=None, description="Current or most recent job title if identifiable."
    )
    preferred_job_role: str = Field(
        description="Must be exactly one of the job titles listed in the prompt (allowed titles)."
    )
    final_verdict: str = Field(description="Short hiring verdict for the chosen role.")
    final_justification: str = Field(
        description="One sentence explaining why that role is the best match."
    )


# --------------------------------------------------
# DELETE request bodies (fn_resume_info / fn_resume_job_match mode 4)
# --------------------------------------------------


class DeleteResumeInfoBody(BaseModel):
    """Bulk delete resume_info by resume_id (SQL: p_resume_ids)."""

    resume_ids: list[UUID] = Field(
        ...,
        min_length=1,
        description="One or more resume_id values to delete.",
    )


class DeleteResumeJobMatchBody(BaseModel):
    """Bulk delete resume_job_match by match_id (SQL mode 4)."""

    match_ids: list[UUID] = Field(
        ...,
        min_length=1,
        description="One or more match_id values to delete.",
    )


class PromoteFromMatchBody(BaseModel):
    """Promote a stored job match into resume_info + evaluation (preferred_jd_id required)."""

    match_id: UUID = Field(
        description="resume_job_match.match_id from a prior POST /resume-job-match."
    )
