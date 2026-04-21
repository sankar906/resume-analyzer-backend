"""Resume evaluation: list (GET), evaluate JSON (POST), full upload pipeline (POST)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder

from src.api.v1.endpoints.llm_gemini import run_evaluation, run_extraction
from src.api.v1.endpoints.resume_info import (
    fetch_resume_info_by_resume_ids,
    insert_resume_info,
    normalize_upload_to_pdf_bytes,
    safe_resume_filename,
    save_resume_pdf,
)
from src.db.manager import db_manager
from src.schemas.common import BaseResponse
from src.schemas.resume import (
    DeleteResumeEvaluationBody,
    EvaluateRequest,
    EvaluationOutput,
    is_substantive_resume_inline_dict,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _evaluate_uses_inline_json(req: EvaluateRequest) -> bool:
    """True only when resume_id is omitted and inline JSON is substantive; resume_id always uses DB."""
    if (req.resume_id or "").strip():
        return False
    j = req.extracted_resume_json
    if j is None:
        return False
    return is_substantive_resume_inline_dict(j)


_FN = "public.fn_resume_evaluation"


def parse_jd_uuid(jd_id: str) -> str | None:
    try:
        return str(uuid.UUID(jd_id.strip()))
    except (ValueError, AttributeError):
        return None


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
        None,    # $11 p_jd_title
        None,    # $12 p_jd_id      (scalar uuid — must be None)
        ev_ids,  # $13 p_resume_ev_ids (uuid[]) ← correct slot
        None,    # $14 p_resume_ids
        None,    # $15 p_jd_ids
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


async def fetch_job_description_by_id(jd_id: str) -> dict[str, Any] | None:
    """Load one job_description row (fn_job_description mode 1)."""
    parsed = parse_jd_uuid(jd_id)
    if not parsed:
        return None
    try:
        rows = await db_manager.execute_function("public.fn_job_description", 1, parsed)
    except Exception:
        return None
    if not rows:
        return None
    return dict(rows[0])


def _jd_title_from_db_row(jd_row: dict[str, Any]) -> str:
    t = jd_row.get("title")
    return str(t).strip() if t is not None else ""


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


@router.get("", response_model=BaseResponse)
async def list_resume_evaluation(
    resume_ev_id: UUID | None = Query(
        default=None,
        description="Exact evaluation row id (sent to DB as a single-element id list).",
    ),
    resume_id: UUID | None = Query(
        default=None,
        description="Resume id filter (sent to DB as a single-element id list).",
    ),
    jd_id: UUID | None = Query(
        default=None,
        description="Job description id filter (sent to DB as a single-element id list).",
    ),
    final_rating: int | None = Query(default=None),
    final_verdict: str | None = Query(default=None),
    jd_title: str | None = Query(default=None),
    limit: int | None = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List or filter resume_evaluation rows (fn_resume_evaluation mode 2)."""
    resume_ev_ids_arg = [str(resume_ev_id)] if resume_ev_id else None
    resume_ids_arg = [str(resume_id)] if resume_id else None
    jd_ids_arg = [str(jd_id)] if jd_id else None
    try:
        rows = await db_manager.execute_function(
            _FN,
            2,
            None,
            None,
            limit,
            offset,
            None,
            final_rating,
            final_verdict,
            None,
            None,
            jd_title,
            None,
            resume_ev_ids_arg,
            resume_ids_arg,
            jd_ids_arg,
        )
    except Exception as e:
        logger.warning("resume-evaluation GET failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    evals_by_resume: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unique_rids: list[str] = []
    seen_rid: set[str] = set()
    for ev in rows:
        rid = ev.get("resume_id")
        if rid is None:
            continue
        s = str(rid)
        evals_by_resume[s].append(ev)
        if s not in seen_rid:
            seen_rid.add(s)
            unique_rids.append(s)

    info_by_rid: dict[str, dict[str, Any]] = {}
    if unique_rids:
        try:
            info_rows = await fetch_resume_info_by_resume_ids(unique_rids)
            for r in info_rows:
                if r.get("resume_id") is not None:
                    info_by_rid[str(r["resume_id"])] = dict(r)
        except Exception as e:
            logger.warning("resume-evaluation GET: resume_info fetch failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e)) from e

    items: list[dict[str, Any]] = []
    for rid in unique_rids:
        base: dict[str, Any] = (
            dict(info_by_rid[rid]) if rid in info_by_rid else {"resume_id": rid}
        )
        base["evaluations"] = evals_by_resume.get(rid, [])
        items.append(jsonable_encoder(base))

    return BaseResponse(
        message="Resume evaluations retrieved successfully.",
        data={
            "count": len(items),
            "items": items,
        },
    )


@router.delete("", response_model=BaseResponse)
async def delete_resume_evaluations(body: DeleteResumeEvaluationBody):
    """Delete resume_evaluation rows (fn_resume_evaluation mode 4). JSON body uses id arrays only.

    SQL combines filters with OR: rows matching any supplied criterion are deleted.
    """
    ev_ids_arg = [str(x) for x in body.resume_ev_ids] if body.resume_ev_ids else None
    r_ids_arg = [str(x) for x in body.resume_ids] if body.resume_ids else None
    jd_ids_arg = [str(x) for x in body.jd_ids] if body.jd_ids else None

    try:
        rows = await db_manager.execute_function(
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
            ev_ids_arg,
            r_ids_arg,
            jd_ids_arg,
        )
    except Exception as e:
        logger.warning("resume-evaluation DELETE failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    encoded = jsonable_encoder(rows)
    return BaseResponse(
        message="Resume evaluations deleted successfully.",
        data={
            "count": len(rows),
            "deleted": encoded,
        },
    )


@router.post("/evaluate", response_model=BaseResponse)
async def evaluate_resume(request: EvaluateRequest):
    """Evaluate resume: either inline JSON or candidate loaded from resume_info by resume_id."""
    use_inline = _evaluate_uses_inline_json(request)
    logger.info(
        "resume-evaluation/evaluate: mode=%s jd_id=%s resume_id=%s",
        "inline_json" if use_inline else "fetch_resume_info",
        request.jd_id,
        request.resume_id,
    )

    jd_row = await fetch_job_description_by_id(request.jd_id)
    if not jd_row:
        raise HTTPException(
            status_code=404,
            detail="Job description not found for the given jd_id.",
        )

    jd_title_db = _jd_title_from_db_row(jd_row)
    resume_id_str = (request.resume_id or "").strip()

    if use_inline:
        try:
            resume_json = json.dumps(request.extracted_resume_json)
        except (TypeError, ValueError) as e:
            raise HTTPException(
                status_code=422, detail=f"Invalid resume JSON: {e}"
            ) from e
        resume_path_val = (request.resume_path or "").strip()
        if not resume_id_str:
            resume_id_str = str(uuid.uuid4())
    else:
        try:
            rows = await fetch_resume_info_by_resume_ids([resume_id_str])
        except Exception as e:
            logger.exception("evaluate: fetch resume_info failed")
            raise HTTPException(status_code=500, detail=f"Database error: {e}") from e
        if not rows:
            raise HTTPException(
                status_code=404,
                detail="Resume not found for the given resume_id.",
            )
        info_row = dict(rows[0])
        payload = _resume_info_row_to_eval_payload(info_row)
        resume_json = json.dumps(payload)
        db_path = info_row.get("resume_path")
        resume_path_val = (
            (request.resume_path or "").strip()
            if request.resume_path and str(request.resume_path).strip()
            else (str(db_path).strip() if db_path else "")
        )
        resume_id_str = str(info_row.get("resume_id", resume_id_str))

    try:
        eval_out = await run_evaluation(resume_json, jd_row=jd_row)
    except Exception as e:
        logger.exception(
            "resume-evaluation/evaluate: gemini failed resume_id=%s",
            resume_id_str,
        )
        raise HTTPException(
            status_code=500, detail=f"Gemini evaluation failed: {e}"
        ) from e

    try:
        row = await insert_evaluation(
            resume_id_str,
            eval_out,
            resume_path_val,
            request.jd_id,
            jd_title_db,
        )
    except Exception as e:
        logger.exception(
            "resume-evaluation/evaluate: db insert failed resume_id=%s",
            resume_id_str,
        )
        raise HTTPException(status_code=500, detail=f"DB insert failed: {e}") from e

    logger.info("resume-evaluation/evaluate: db inserted id=%s", row["resume_ev_id"])

    logger.info(
        "resume-evaluation/evaluate: done evaluation_id=%s resume_id=%s",
        row["resume_ev_id"],
        resume_id_str,
    )
    return BaseResponse(
        success=True,
        message="Evaluation completed and stored successfully.",
        data={
            "evaluation_id": str(row["resume_ev_id"]),
            "evaluation": eval_out.model_dump(mode="json"),
        },
    )


@router.post("/upload", response_model=BaseResponse)
async def upload_resume(
    file: UploadFile = File(...),
    jd_id: str = Form(...),
):
    """Extract PDF or Word doc, save file, insert resume_info, evaluate, insert evaluation."""
    jd_row = await fetch_job_description_by_id(jd_id)
    if not jd_row:
        raise HTTPException(
            status_code=404,
            detail="Job description not found for the given jd_id.",
        )

    jd_title_db = _jd_title_from_db_row(jd_row)

    pdf_bytes = await normalize_upload_to_pdf_bytes(file)
    try:
        info = await run_extraction(pdf_bytes)
    except Exception as e:
        logger.warning("resume-evaluation/upload: extraction failed: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Gemini extraction failed: {e}"
        ) from e
    resume_uuid = uuid.uuid4()
    resume_path = f"{safe_resume_filename(info.name)}_{resume_uuid}.pdf"

    try:
        save_resume_pdf(pdf_bytes, resume_path)
    except Exception as e:
        logger.warning("resume-evaluation/upload: file save failed: %s", e)
        raise HTTPException(status_code=500, detail=f"File save failed: {e}") from e

    try:
        info_row = await insert_resume_info(resume_uuid, info, resume_path)
    except Exception as e:
        logger.warning("resume-evaluation/upload: resume_info insert failed: %s", e)
        raise HTTPException(
            status_code=500, detail=f"DB insert (resume_info) failed: {e}"
        ) from e

    logger.info(
        "resume-evaluation/upload: db inserted resume_info id=%s", info_row["resume_id"]
    )

    resume_id = str(info_row["resume_id"])

    await asyncio.sleep(2)
    try:
        eval_out = await run_evaluation(info.model_dump_json(), jd_row=jd_row)
    except Exception as e:
        logger.warning(
            "resume-evaluation/upload: evaluation failed resume_id=%s: %s",
            resume_id,
            e,
        )
        raise HTTPException(
            status_code=500, detail=f"Gemini evaluation failed: {e}"
        ) from e

    try:
        eval_row = await insert_evaluation(
            resume_id, eval_out, resume_path, jd_id, jd_title_db
        )
    except Exception as e:
        logger.warning(
            "resume-evaluation/upload: resume_evaluation insert failed resume_id=%s: %s",
            resume_id,
            e,
        )
        raise HTTPException(
            status_code=500, detail=f"DB insert (resume_evaluation) failed: {e}"
        ) from e

    logger.info(
        "resume-evaluation/upload: db inserted resume_evaluation id=%s",
        eval_row["resume_ev_id"],
    )

    logger.info(
        "resume-evaluation/upload: done resume_id=%s evaluation_id=%s path=%s",
        resume_id,
        eval_row["resume_ev_id"],
        resume_path,
    )
    return BaseResponse(
        success=True,
        message="Resume processed and evaluated successfully.",
        data={
            "resume_id": resume_id,
            "evaluation_id": str(eval_row["resume_ev_id"]),
            "resume_path": resume_path,
            "extracted_data": info.model_dump(mode="json"),
            "evaluation": eval_out.model_dump(mode="json"),
        },
    )
