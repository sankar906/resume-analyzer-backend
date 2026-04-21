"""Schemas for requirements-aligned resume evaluation (LLM + DB)."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Resume-assessed proficiency for this line (must match LLM prompt; lowercase in JSON).
CandidateProficiencyLevel = Literal[
    "awareness",
    "basic",
    "intermediate",
    "advanced",
    "experience",
]

_CANDIDATE_LEVELS: tuple[str, ...] = (
    "awareness",
    "basic",
    "intermediate",
    "advanced",
    "experience",
)


class RequirementLineEval(BaseModel):
    """One row under a requirement section (skill vs JD vs assessed level)."""

    skill: str = Field(description="Subject/skill name from the job requirements.")
    expected: str = Field(description="Expected level/text from the job requirements.")
    candidate: CandidateProficiencyLevel = Field(
        description=(
            "Assessed proficiency from the resume for this skill; exactly one of: "
            "awareness, basic, intermediate, advanced, experience."
        ),
    )
    rating: int = Field(ge=1, le=100, description="Score 1–100 for this line item.")

    @field_validator("candidate", mode="before")
    @classmethod
    def normalize_candidate_level(cls, v: Any) -> str:
        """Coerce casing/typos; map legacy free-text evidence to a level when obvious."""
        if v is None:
            return "awareness"
        s = str(v).strip().lower()
        if s == "experince":
            s = "experience"
        if s in _CANDIDATE_LEVELS:
            return s
        # Long evidence-style strings from older prompts → lowest defensible bucket
        if len(s) > 50 or any(
            phrase in s
            for phrase in (
                "no explicit",
                "no mention",
                "not found",
                "no evidence",
                "does not mention",
                "lack of",
                "not demonstrated",
            )
        ):
            return "awareness"
        for level in _CANDIDATE_LEVELS:
            if s == level.capitalize() or s == level.upper():
                return level
        return "awareness"


class RequirementsAlignedEvalOutput(BaseModel):
    """Gemini JSON output for POST /candidates."""

    candidate_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    years_of_experience: Optional[float] = None
    present_role: Optional[str] = None
    evaluations: dict[str, list[RequirementLineEval]] = Field(
        default_factory=dict,
        description='Keys = section titles from job Requirements (e.g. "Technical skills").',
    )
    final_rating: int = Field(ge=0, le=100, description="Overall score 0–100.")
    final_verdict: str = Field(description="Short hiring verdict.")
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
