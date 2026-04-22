"""DB helpers for legacy public.resume_evaluation (fn_resume_evaluation). Used by resume_job_match /promote only."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.api.v1.endpoints.jd_fetch import parse_jd_uuid
from src.db.manager import db_manager
from src.schemas.resume import EvaluationOutput

logger = logging.getLogger(__name__)

_FN = "public.fn_resume_evaluation"


def _evaluation_row_created_at(row: dict[str, Any]) -> Any:
    """Prefer created_at; fall back to created. Newest wins per (resume_id, jd_id)."""
    for key in ("created_at", "created"):
        v = row.get(key)
        if v is not None:
            return v
    return None


def _sort_evaluation_rows_newest_first(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    def sort_key(r: dict[str, Any]) -> tuple:
        ts = _evaluation_row_created_at(r)
        ev = str(r.get("resume_ev_id", ""))
        if ts is None:
            return (False, ev)
        return (True, ts, ev)

    return sorted(rows, key=sort_key, reverse=True)


async def _fetch_evaluations_for_resume_jd(
    resume_id: str, jd_id: str
) -> list[dict[str, Any]]:
    """fn_resume_evaluation mode 2: rows for this resume_id and jd_id."""
    parsed = parse_jd_uuid(jd_id)
    if not parsed:
        return []
    resume_ids_arg = [str(resume_id)]
    jd_ids_arg = [parsed]
    return await db_manager.execute_function(
        _FN,
        2,
        None,
        None,
        500,
        0,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        resume_ids_arg,
        jd_ids_arg,
    )


async def _delete_evaluations_by_ev_ids(ev_ids: list[str]) -> None:
    """fn_resume_evaluation mode 4: delete by resume_ev_id list only."""
    if not ev_ids:
        return
    await db_manager.execute_function(
        _FN,
        4,
        None,
        None,
        None,
        0,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        ev_ids,
        None,
        None,
    )


async def _dedupe_evaluations_for_resume_jd(resume_id: str, jd_id: str) -> None:
    """Keep newest row per (resume_id, jd_id) by created time; delete older duplicates."""
    rows = await _fetch_evaluations_for_resume_jd(resume_id, jd_id)
    if len(rows) <= 1:
        return
    ordered = _sort_evaluation_rows_newest_first(rows)
    keep = ordered[0]
    keep_id = keep.get("resume_ev_id")
    stale_ids: list[str] = []
    for r in ordered[1:]:
        ev_id = r.get("resume_ev_id")
        if ev_id is not None and str(ev_id) != str(keep_id):
            stale_ids.append(str(ev_id))
    if not stale_ids:
        return
    await _delete_evaluations_by_ev_ids(stale_ids)
    logger.info(
        "deduped resume_evaluation: resume_id=%s jd_id=%s kept=%s removed=%s",
        resume_id,
        parse_jd_uuid(jd_id),
        keep_id,
        stale_ids,
    )


def _coerce_jsonb(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, str) and val.strip().startswith(("{", "[")):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val
    return val


def _resume_info_row_to_eval_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Map resume_info DB row to ResumeInfo-shaped dict for the evaluator prompt."""
    tey = row.get("total_experience_years")
    if tey is not None:
        try:
            tey = float(tey)
        except (TypeError, ValueError):
            tey = None

    def arr_or_empty(key: str) -> Any:
        v = _coerce_jsonb(row.get(key))
        if v is None:
            return [] if key in ("skills", "experience", "education") else None
        return v

    return {
        "name": row.get("candidate_name"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "location": row.get("location"),
        "linkedin": row.get("linkedin"),
        "summary": row.get("summary"),
        "total_experience_years": tey,
        "current_role": row.get("currentrole"),
        "skills": arr_or_empty("skills") or [],
        "experience": arr_or_empty("experience") or [],
        "education": arr_or_empty("education") or [],
        "projects": arr_or_empty("projects"),
        "certifications": arr_or_empty("certifications"),
        "languages": arr_or_empty("languages"),
    }


async def insert_evaluation(
    resume_id: str,
    eval_out: EvaluationOutput,
    resume_path: str,
    jd_id: str,
    jd_title: str,
) -> dict:
    evaluation_jsonb = {
        "knowledge_areas": eval_out.knowledge_areas.model_dump(),
        "technical_skills": eval_out.technical_skills.model_dump(),
        "experience": eval_out.experience.model_dump(),
        "certifications": eval_out.certifications.model_dump()
        if eval_out.certifications
        else None,
    }
    rows = await db_manager.execute_function(
        _FN,
        1,
        None,
        resume_id,
        None,
        0,
        evaluation_jsonb,
        eval_out.final_rating,
        eval_out.final_verdict,
        eval_out.final_justification,
        resume_path,
        jd_title.strip() if jd_title else None,
        parse_jd_uuid(jd_id),
        None,
        None,
        None,
    )
    if not rows:
        raise RuntimeError(
            "fn_resume_evaluation insert returned no rows — DB constraint may have rejected the insert."
        )
    row = rows[0]
    try:
        await _dedupe_evaluations_for_resume_jd(str(resume_id), jd_id)
    except Exception:
        logger.warning(
            "insert_evaluation: dedupe failed resume_id=%s jd_id=%s",
            resume_id,
            jd_id,
            exc_info=True,
        )
    return row
