"""Pydantic models for resume extraction and evaluation."""

from datetime import date
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


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
# Request model for evaluate endpoint
# --------------------------------------------------

_RESUME_INLINE_FIELD_NAMES = frozenset(
    {
        "name",
        "phone",
        "location",
        "linkedin",
        "summary",
        "total_experience_years",
        "current_role",
        "skills",
        "experience",
        "education",
        "projects",
        "certifications",
        "languages",
    }
)


def is_substantive_resume_inline_dict(d: object) -> bool:
    """
    True only if the dict looks like a real resume payload (ResumeInfo-shaped).
    Swagger/OpenAPI placeholders like {\"additionalProp1\": {}} are not substantive.
    """
    if not isinstance(d, dict) or not d:
        return False
    for key in _RESUME_INLINE_FIELD_NAMES:
        if key not in d:
            continue
        val = d[key]
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        if isinstance(val, (list, dict)) and len(val) == 0:
            continue
        return True
    return False


class EvaluateRequest(BaseModel):
    jd_id: str = Field(description="Job description UUID from job_description.")
    resume_id: Optional[str] = Field(
        default=None,
        description="Resume UUID from resume_info. If set (non-empty), candidate data is always "
        "loaded from the database; extracted_resume_json is ignored.",
    )
    extracted_resume_json: Optional[dict] = Field(
        default=None,
        description="Inline resume (ResumeInfo-shaped). Used only when resume_id is omitted; "
        "ignored whenever resume_id is present.",
    )
    resume_path: Optional[str] = Field(
        default=None,
        description="File path for inline resume when resume_id is omitted; optional when loading by resume_id.",
    )

    @model_validator(mode="after")
    def resume_source(self) -> "EvaluateRequest":
        rid = (self.resume_id or "").strip()
        if rid:
            # resume_id has priority: DB load; do not require resume_path or substantive JSON.
            return self
        j = self.extracted_resume_json
        has_inline = j is not None and is_substantive_resume_inline_dict(j)
        if has_inline:
            if not (self.resume_path and str(self.resume_path).strip()):
                raise ValueError(
                    "resume_path is required when using inline resume without resume_id."
                )
        else:
            raise ValueError(
                "Provide resume_id to load from DB, or omit resume_id and send "
                "substantive extracted_resume_json with resume_path."
            )
        return self


# --------------------------------------------------
# DELETE request bodies (fn_resume_info / fn_resume_evaluation / fn_resume_job_match mode 4)
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


class DeleteResumeEvaluationBody(BaseModel):
    """Delete resume_evaluation rows (SQL mode 4). Use non-empty id arrays only (OR semantics).

    Pass a single id as a one-element list, e.g. {\"resume_ids\": [\"<uuid>\"]}.
    """

    resume_ev_ids: list[UUID] | None = None
    resume_ids: list[UUID] | None = None
    jd_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def at_least_one_non_empty_list(self):
        has_ev = bool(self.resume_ev_ids and len(self.resume_ev_ids) > 0)
        has_r = bool(self.resume_ids and len(self.resume_ids) > 0)
        has_jd = bool(self.jd_ids and len(self.jd_ids) > 0)
        if not (has_ev or has_r or has_jd):
            raise ValueError(
                "Provide at least one non-empty array: resume_ev_ids, resume_ids, or jd_ids."
            )
        return self
