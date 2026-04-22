"""Schemas for candidate evaluation (LLM output + DB) for POST /candidates."""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class CandidateEvalLine(BaseModel):
    """One row under a requirement section (skill vs JD vs assessed level)."""

    skill: str = Field(description="Subject/skill name from the job requirements.")
    expected: str = Field(description="Expected level/text from the job requirements.")
    candidate: str = Field(
        description=(
            "Assessed proficiency or evidence from the model for this line "
            "(exactly one of - awareness | basic | intermediate | advanced | expert)."
        ),
    )
    rating: int = Field(ge=1, le=100, description="Score 1–100 for this line item.")

    @field_validator("candidate", mode="before")
    @classmethod
    def candidate_passthrough(cls, v: Any) -> str:
        """Preserve model output; only normalize null."""
        if v is None:
            return ""
        return str(v)


class CandidatesEvalOutput(BaseModel):
    """Gemini JSON output for POST /candidates."""

    candidate_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    years_of_experience: Optional[float] = None
    present_role: Optional[str] = None
    evaluations: dict[str, list[CandidateEvalLine]] = Field(
        default_factory=dict,
        description='Keys = section titles from job Requirements (e.g. "Technical skills").',
    )
    final_rating: int = Field(ge=0, le=100, description="Overall score 0–100.")
    final_verdict: str = Field(
        description="Short hiring verdict. exactly one of — Strong Hire | Hire | Borderline | Reject"
    )
    final_justification: str = Field(description="One-sentence justification.")

    @field_validator("years_of_experience", mode="before")
    @classmethod
    def coerce_years_of_experience(cls, v: Any) -> float | None:
        """LLMs often return strings like \"4+\" or \"5 years\"; take the leading number."""
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            if not s:
                return None
            m = re.match(r"^(\d+(?:\.\d+)?)", s)
            if m:
                return float(m.group(1))
            return None
        return None
