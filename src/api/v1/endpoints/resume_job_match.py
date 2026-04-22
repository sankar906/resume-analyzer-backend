"""Resume PDF + one or more job descriptions → Gemini match → persist scalar columns."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder

from src.api.v1.endpoints.llm_gemini import (
    build_job_match_prompt,
    run_extraction,
    run_evaluation,
    run_resume_job_match_pdf,
)
from src.api.v1.endpoints.jd_fetch import (
    _jd_title_from_db_row,
    fetch_job_description_by_id,
)
from src.api.v1.endpoints.resume_eval_db import (
    _resume_info_row_to_eval_payload,
    insert_evaluation,
)
from src.api.v1.endpoints.resume_info import (
    fetch_resume_info_by_resume_ids,
    insert_resume_info,
    normalize_upload_to_pdf_bytes,
    resolve_stored_resume_file,
    resume_path_for_db_from_basename,
    safe_resume_filename,
    save_resume_pdf,
)
from src.api.v1.prompts.eval_injection import build_job_context_from_row
from src.db.manager import db_manager
from src.schemas.common import BaseResponse
from src.schemas.resume import (
    DeleteResumeJobMatchBody,
    PromoteFromMatchBody,
    ResumeJobMatchOutput,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_FN = "public.fn_resume_job_match"
_FN_JD = "public.fn_job_description"


async def fetch_all_job_jd_ids() -> list[str]:
    """All jd_id values from job_description (fn_job_description mode 1, p_jd_id NULL)."""
    rows = await db_manager.execute_function(_FN_JD, 1, None)
    ids = [str(r["jd_id"]) for r in rows if r.get("jd_id") is not None]
    ids.sort()
    return ids


def _jd_display_title(row: dict[str, Any], override: str | None) -> str:
    if override and str(override).strip():
        return str(override).strip()
    t = row.get("title")
    return str(t).strip() if t is not None else "Untitled role"


def parse_jobs_json(raw: str) -> tuple[list[str], dict[str, str]]:
    """
    Parse Form `jobs` JSON.
    - List: ["uuid", ...] (order preserved)
    - Dict: {"uuid": "optional title", ...} (insertion order preserved)
    Returns (ordered_jd_id_strings, title_overrides_by_jd_id).
    """
    s = (raw or "").strip()
    if not s:
        raise ValueError("jobs is required (JSON array of UUIDs or object uuid->title).")
    data = json.loads(s)
    overrides: dict[str, str] = {}
    if isinstance(data, list):
        if not data:
            raise ValueError("jobs array must not be empty.")
        out: list[str] = []
        for x in data:
            out.append(str(uuid.UUID(str(x).strip())))
        return out, overrides
    if isinstance(data, dict):
        if not data:
            raise ValueError("jobs object must not be empty.")
        out_ids: list[str] = []
        for k, v in data.items():
            kid = str(uuid.UUID(str(k).strip()))
            out_ids.append(kid)
            if v is not None and str(v).strip():
                overrides[kid] = str(v).strip()
        return out_ids, overrides
    raise ValueError("jobs must be a JSON array of UUID strings or an object of uuid->title.")


def _coerce_preferred_to_allowed(chosen: str, allowed: list[str]) -> str:
    c = chosen.strip()
    for a in allowed:
        if c == a:
            return a
    cf = c.casefold()
    for a in allowed:
        if a.casefold() == cf:
            return a
    raise ValueError(
        f'preferred_job_role "{chosen}" must be exactly one of: {allowed!r}'
    )


def resolve_preferred_jd_id(
    preferred_title: str,
    jd_rows: list[tuple[str, dict[str, Any], str]],
) -> uuid.UUID:
    """Map coerced preferred_job_role to jd_id (first row whose display title matches)."""
    for jid, _row, title in jd_rows:
        if title == preferred_title:
            return uuid.UUID(jid)
    raise RuntimeError("preferred_job_role did not resolve to a jd_id (internal error).")


async def insert_resume_job_match_row(
    resume_path: str,
    out: ResumeJobMatchOutput,
    jd_ids: list[str],
    preferred_jd_id: uuid.UUID,
) -> dict[str, Any]:
    jd_uuids = [uuid.UUID(x) for x in jd_ids]
    rows = await db_manager.execute_function(
        _FN,
        1,
        resume_path,
        out.name,
        out.email,
        out.phone,
        out.currentrole,
        out.preferred_job_role,
        preferred_jd_id,
        out.final_verdict,
        out.final_justification,
        jd_uuids,
        None,
        None,
        None,
        None,
        False,
    )
    if not rows:
        raise RuntimeError("fn_resume_job_match insert returned no rows.")
    return dict(rows[0])


async def fetch_job_match_by_match_id(match_id: uuid.UUID) -> dict[str, Any]:
    # Args align with fn_resume_job_match: ... p_jd_ids ($11), p_match_id ($12), ...
    rows = await db_manager.execute_function(
        _FN,
        2,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        match_id,
        None,
        None,
        None,
        None,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Job match not found.")
    return dict(rows[0])


async def mark_job_match_added_to_resume_info(match_id: uuid.UUID) -> None:
    """fn_resume_job_match mode 5: set added_to_resume_info = true."""
    await db_manager.execute_function(
        _FN,
        5,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        match_id,
        None,
        None,
        None,
        True,
    )


@router.post("", response_model=BaseResponse)
async def match_resume_to_jobs(
    file: UploadFile = File(...),
    jobs: str | None = Form(
        default=None,
        description='Optional JSON: ["jd-uuid", ...] or {"uuid": "title", ...}. '
        "Omit, leave empty, or use [] / {} to match against all job descriptions.",
    ),
):
    """
    Upload a resume (PDF/DOC/DOCX → stored as PDF). Send PDF + prompt to Gemini.
    Persist one row per request with scalar columns (no JSON blob for LLM fields).
    """
    filename_stem = Path(file.filename or "resume").stem or "resume"
    title_overrides: dict[str, str] = {}
    raw_jobs = (jobs or "").strip()
    if not raw_jobs:
        jd_ids = await fetch_all_job_jd_ids()
    else:
        try:
            payload = json.loads(raw_jobs)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=422, detail=f"Invalid jobs JSON: {e}") from e
        if isinstance(payload, list) and len(payload) == 0:
            jd_ids = await fetch_all_job_jd_ids()
        elif isinstance(payload, dict) and len(payload) == 0:
            jd_ids = await fetch_all_job_jd_ids()
        else:
            try:
                jd_ids, title_overrides = parse_jobs_json(jobs)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e

    if not jd_ids:
        raise HTTPException(
            status_code=422,
            detail="No job descriptions found. Add job descriptions before running a match.",
        )

    jd_rows: list[tuple[str, dict[str, Any], str]] = []
    allowed_titles: list[str] = []
    for jid in jd_ids:
        row = await fetch_job_description_by_id(jid)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Job description not found for jd_id={jid}.",
            )
        title = _jd_display_title(row, title_overrides.get(jid))
        allowed_titles.append(title)
        jd_rows.append((jid, dict(row), title))

    contexts: list[str] = []
    for i, (_jid, row, title) in enumerate(jd_rows, start=1):
        body = build_job_context_from_row(row)
        if not body.strip():
            body = "(No job description field values were available for the selected keys.)"
        contexts.append(f"### Job {i}: {title}\n{body}")
    job_contexts = "\n\n".join(contexts)

    prompt = build_job_match_prompt(
        single_job=len(jd_rows) == 1,
        allowed_titles=allowed_titles,
        job_contexts=job_contexts,
    )

    try:
        Path("prompt2.txt").write_text(prompt, encoding="utf-8")
    except OSError as e:
        logger.warning("resume-job-match: could not write prompt2.txt: %s", e)

    pdf_bytes = await normalize_upload_to_pdf_bytes(file)
    resume_path = f"{safe_resume_filename(filename_stem)}_{uuid.uuid4()}.pdf"

    try:
        save_resume_pdf(pdf_bytes, resume_path)
    except Exception as e:
        logger.warning("resume-job-match: file save failed: %s", e)
        raise HTTPException(status_code=500, detail=f"File save failed: {e}") from e

    try:
        resume_path_db = resume_path_for_db_from_basename(resume_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        raw_out = await run_resume_job_match_pdf(pdf_bytes, prompt)
    except Exception as e:
        logger.exception("resume-job-match: Gemini failed")
        raise HTTPException(status_code=500, detail=f"Gemini job match failed: {e}") from e

    try:
        preferred = _coerce_preferred_to_allowed(raw_out.preferred_job_role, allowed_titles)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    out = raw_out.model_copy(update={"preferred_job_role": preferred})
    preferred_jd = resolve_preferred_jd_id(preferred, jd_rows)

    try:
        row = await insert_resume_job_match_row(resume_path_db, out, jd_ids, preferred_jd)
    except Exception as e:
        logger.exception("resume-job-match: DB insert failed")
        raise HTTPException(status_code=500, detail=f"DB insert failed: {e}") from e

    mid = row.get("match_id")
    data = {
        "match_id": str(mid) if mid is not None else None,
        "resume_path": resume_path_db,
        "name": row.get("name"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "currentrole": row.get("currentrole"),
        "preferred_job_role": row.get("preferred_job_role"),
        "preferred_jd_id": str(row.get("preferred_jd_id"))
        if row.get("preferred_jd_id") is not None
        else None,
        "final_verdict": row.get("final_verdict"),
        "final_justification": row.get("final_justification"),
        "jd_ids": [str(x) for x in jd_ids],
    }
    return BaseResponse(
        success=True,
        message="Resume matched to job(s) and stored successfully.",
        data=jsonable_encoder(data),
    )


@router.post("/promote", response_model=BaseResponse)
async def promote_job_match_to_resume_info_and_evaluate(body: PromoteFromMatchBody):
    """
    Load a stored job match by match_id, re-extract the PDF from disk (no new save),
    insert resume_info, then evaluate against preferred_jd_id (Gemini + DB row).
    """
    match_uuid = uuid.UUID(str(body.match_id))
    m = await fetch_job_match_by_match_id(match_uuid)
    file_path = resolve_stored_resume_file(m.get("resume_path"))
    if file_path is None:
        raise HTTPException(
            status_code=422, detail="Invalid resume_path on job match row."
        )

    pref = m.get("preferred_jd_id")
    if pref is None:
        raise HTTPException(
            status_code=422,
            detail="Job match has no preferred_jd_id; cannot evaluate.",
        )
    jd_id_str = str(pref)

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Resume file not found: {file_path.name}",
        )

    pdf_bytes = file_path.read_bytes()
    try:
        info = await run_extraction(pdf_bytes)
    except Exception as e:
        logger.exception("resume-job-match/promote: extraction failed")
        raise HTTPException(status_code=500, detail=f"Gemini extraction failed: {e}") from e

    resume_uuid = uuid.uuid4()
    try:
        info_row = await insert_resume_info(resume_uuid, info, str(file_path))
    except Exception as e:
        logger.exception("resume-job-match/promote: resume_info insert failed")
        raise HTTPException(status_code=500, detail=f"DB insert failed: {e}") from e

    resume_id_str = str(info_row["resume_id"])

    jd_row = await fetch_job_description_by_id(jd_id_str)
    if not jd_row:
        raise HTTPException(
            status_code=404,
            detail="Job description not found for preferred_jd_id.",
        )

    try:
        ri_rows = await fetch_resume_info_by_resume_ids([resume_id_str])
    except Exception as e:
        logger.exception("resume-job-match/promote: fetch resume_info failed")
        raise HTTPException(status_code=500, detail=f"Database error: {e}") from e
    if not ri_rows:
        raise HTTPException(status_code=500, detail="Resume not found after insert.")
    info_row_db = dict(ri_rows[0])
    payload = _resume_info_row_to_eval_payload(info_row_db)
    resume_json = json.dumps(payload)
    db_path = info_row_db.get("resume_path")
    resume_path_val = str(db_path).strip() if db_path else ""

    jd_title_db = _jd_title_from_db_row(jd_row)
    try:
        eval_out = await run_evaluation(resume_json, jd_row=jd_row)
    except Exception as e:
        logger.exception("resume-job-match/promote: Gemini evaluation failed")
        raise HTTPException(status_code=500, detail=f"Gemini evaluation failed: {e}") from e

    try:
        ev_row = await insert_evaluation(
            resume_id_str,
            eval_out,
            resume_path_val,
            jd_id_str,
            jd_title_db,
        )
    except Exception as e:
        logger.exception("resume-job-match/promote: evaluation insert failed")
        raise HTTPException(status_code=500, detail=f"Evaluation DB insert failed: {e}") from e

    try:
        await mark_job_match_added_to_resume_info(match_uuid)
    except Exception as e:
        logger.exception("resume-job-match/promote: added_to_resume_info update failed")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to mark job match as added to resume_info: {e}",
        ) from e

    return BaseResponse(
        success=True,
        message="Resume extracted, stored, and evaluated from job match.",
        data=jsonable_encoder(
            {
                "match_id": str(match_uuid),
                "resume_id": resume_id_str,
                "resume_path": str(file_path),
                "evaluation_id": str(ev_row["resume_ev_id"]),
                "extracted_data": info.model_dump(mode="json"),
                "evaluation": eval_out.model_dump(mode="json"),
                "added_to_resume_info": True,
            }
        ),
    )


@router.get("", response_model=BaseResponse)
async def list_resume_job_matches(
    match_id: UUID | None = Query(default=None, description="Single match_id filter."),
    match_ids: list[UUID] | None = Query(
        default=None,
        description="Multiple match_id values (repeat query param).",
    ),
    name: str | None = Query(default=None),
    email: str | None = Query(default=None),
    phone: str | None = Query(default=None),
    currentrole: str | None = Query(default=None),
    preferred_job_role: str | None = Query(default=None),
    preferred_jd_id: UUID | None = Query(default=None),
    added_to_resume_info: bool | None = Query(
        default=None,
        description="If set, filter rows where added_to_resume_info equals this value.",
    ),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List/filter resume_job_match rows (fn_resume_job_match mode 2)."""
    if match_id is not None and match_ids:
        raise HTTPException(
            status_code=422,
            detail="Provide either match_id or match_ids, not both.",
        )
    mid = uuid.UUID(str(match_id)) if match_id is not None else None
    mids: list[uuid.UUID] | None = None
    if match_ids:
        mids = [uuid.UUID(str(x)) for x in match_ids]
    pj = uuid.UUID(str(preferred_jd_id)) if preferred_jd_id is not None else None
    try:
        rows = await db_manager.execute_function(
            _FN,
            2,
            None,
            name,
            email,
            phone,
            currentrole,
            preferred_job_role,
            pj,
            None,
            None,
            None,
            mid,
            limit,
            offset,
            mids,
            added_to_resume_info,
        )
    except Exception as e:
        logger.warning("resume-job-match GET failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return BaseResponse(
        success=True,
        message="Resume job match rows retrieved successfully.",
        data={
            "count": len(rows),
            "rows": jsonable_encoder(rows),
        },
    )


@router.delete("", response_model=BaseResponse)
async def delete_resume_job_matches(body: DeleteResumeJobMatchBody):
    """Bulk delete resume_job_match rows by match_id (fn_resume_job_match mode 4)."""
    match_ids = [str(x) for x in body.match_ids]
    try:
        rows = await db_manager.execute_function(
            _FN,
            4,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            match_ids,
            None,
        )
    except Exception as e:
        logger.warning("resume-job-match DELETE failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return BaseResponse(
        success=True,
        message="Resume job match row(s) deleted successfully.",
        data={
            "count": len(rows),
            "deleted": jsonable_encoder(rows),
        },
    )
