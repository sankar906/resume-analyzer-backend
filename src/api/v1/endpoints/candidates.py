"""Candidates API: JD + resume (candidates + candidate_eval tables). No resume_info / resume_evaluation."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from src.api.v1.endpoints.llm_gemini import (
    build_candidates_eval_prompt,
    run_candidates_eval_pdf,
)
from src.api.v1.endpoints.resume_evaluation import (
    _jd_title_from_db_row,
    fetch_job_description_by_id,
)
from src.api.v1.endpoints.resume_info import (
    RESUME_FOLDER,
    normalize_upload_to_pdf_bytes,
    safe_resume_filename,
    save_resume_pdf,
)
from src.api.v1.prompts.eval_injection import build_job_context_from_row
from src.db.manager import db_manager
from src.schemas.common import BaseResponse
from src.schemas.candidates_eval import CandidatesEvalOutput

logger = logging.getLogger(__name__)

router = APIRouter()
_FN_CANDIDATE = "public.fn_candidates"
_FN_RUN = "public.fn_candidate_eval"
# fn_candidates: 14 args after function name — modes 1–3 pad unused tail with None.
_FN_CAND_TAIL6 = (None, None, None, None, None, None)


def _jd_title_for_eval_row(jd_row: dict[str, Any]) -> str | None:
    """Job description title for candidate_eval.jd_title; NULL if missing/empty."""
    t = _jd_title_from_db_row(jd_row)
    return t if t else None


resume_instruction_pdf = (
    "The candidate resume is attached as a PDF. Read the entire document for "
    "contact details, experience, and evidence for each requirement line."
)

# Filenames for saving the full requirements-aligned prompt (cwd): upload vs re-eval.
_PROMPT_DUMP_UPLOAD = "prompt1.txt"
_PROMPT_DUMP_REEVAL = "prompt2.txt"


def _write_candidates_eval_prompt_file(filename: str, prompt: str) -> None:
    """Persist the exact prompt text sent with the PDF to Gemini; failures are non-fatal."""
    try:
        Path(filename).write_text(prompt, encoding="utf-8", newline="\n")
    except OSError:
        logger.warning(
            "candidates eval: could not write prompt file %s", filename, exc_info=True
        )


async def _fetch_candidate_row(candidate_id: str) -> dict[str, Any] | None:
    """fn_candidates mode 2: single row via one-element p_candidate_ids."""
    rows = await db_manager.execute_function(
        _FN_CANDIDATE,
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
        [candidate_id],
        None,
        None,
    )
    if not rows:
        return None
    return dict(rows[0])


# fn_candidates mode 2 caps p_limit at 500 — batch id lists when bulk-loading.
_FN_CANDIDATES_MAX_LIMIT = 500


async def _fetch_candidates_by_ids(
    candidate_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Bulk fetch candidate rows by id (fn_candidates mode 2). Dedupes; map candidate_id -> row."""
    seen: set[str] = set()
    unique: list[str] = []
    for cid in candidate_ids:
        s = str(cid).strip() if cid is not None else ""
        if s and s not in seen:
            seen.add(s)
            unique.append(s)
    if not unique:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(unique), _FN_CANDIDATES_MAX_LIMIT):
        chunk = unique[i : i + _FN_CANDIDATES_MAX_LIMIT]
        rows = await db_manager.execute_function(
            _FN_CANDIDATE,
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
            chunk,
            len(chunk),
            0,
        )
        for r in rows:
            out[str(r["candidate_id"])] = dict(r)
    return out


def _candidate_row_as_list_endpoint(
    base: dict[str, Any], all_evaluations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Same shape as each row in GET /candidates: candidate fields + all_evaluations."""
    row = dict(base)
    row["all_evaluations"] = all_evaluations
    return row


def _evaluation_row_for_response(row: dict[str, Any]) -> dict[str, Any]:
    """Ensure jsonb `evaluations` is a nested object in JSON, not an escaped string."""
    out = dict(row)
    ev = out.get("evaluations")
    if isinstance(ev, str):
        try:
            out["evaluations"] = json.loads(ev)
        except json.JSONDecodeError:
            pass
    return out


async def _evaluations_by_candidate_ids(
    candidate_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """fn_candidate_eval mode 2: all eval rows for the given candidate ids (high limit)."""
    if not candidate_ids:
        return {}
    ev_rows = await db_manager.execute_function(
        _FN_RUN,
        2,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        candidate_ids,
        None,
        None,
        None,
        10000,
        0,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in ev_rows:
        cid = ev.get("candidate_id")
        if cid is None:
            continue
        grouped[str(cid)].append(_evaluation_row_for_response(dict(ev)))
    return dict(grouped)


async def _candidates_eval_pdf(
    pdf_bytes: bytes,
    job_context: str,
    *,
    prompt_dump_filename: str | None = None,
) -> CandidatesEvalOutput:
    prompt = build_candidates_eval_prompt(job_context, resume_instruction_pdf)
    if prompt_dump_filename:
        _write_candidates_eval_prompt_file(prompt_dump_filename, prompt)
    return await run_candidates_eval_pdf(pdf_bytes, prompt)


async def _insert_evaluation_run(
    evaluation_id: uuid.UUID,
    candidate_id: str,
    jd_uuid: Any,
    out: CandidatesEvalOutput,
    jd_title: str | None = None,
) -> list[dict[str, Any]]:
    evaluations_dict: dict[str, Any] = out.model_dump(mode="json")["evaluations"]
    try:
        run_rows = await db_manager.execute_function(
            _FN_RUN,
            1,
            str(evaluation_id),
            candidate_id,
            str(jd_uuid) if jd_uuid is not None else None,
            jd_title,
            evaluations_dict,
            out.final_rating,
            out.final_verdict,
            out.final_justification,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    except Exception as e:
        logger.exception("candidates eval: evaluation insert failed")
        raise HTTPException(
            status_code=500, detail=f"DB insert (evaluation) failed: {e}"
        ) from e
    if not run_rows:
        raise HTTPException(
            status_code=500, detail="Evaluation insert returned no rows."
        )
    return run_rows


def _parse_uuid(raw: str, field: str) -> str:
    try:
        return str(uuid.UUID(raw.strip()))
    except (ValueError, AttributeError) as e:
        raise HTTPException(
            status_code=422, detail=f"Invalid {field} UUID: {raw!r}."
        ) from e


def _parse_uuid_opt(raw: str | None, field: str) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    return _parse_uuid(str(raw).strip(), field)


def _nonempty_str_list(items: list[str] | None) -> list[str] | None:
    if not items:
        return None
    cleaned = [x.strip() for x in items if x is not None and str(x).strip()]
    return cleaned or None


@router.get("/evaluations", response_model=BaseResponse)
async def list_candidate_evaluations(
    evaluation_id: str | None = Query(None, description="Exact evaluation_id."),
    candidate_id: str | None = Query(None, description="Exact candidate_id."),
    jd_id: str | None = Query(None, description="Exact jd_id."),
    candidate_ids: list[str] | None = Query(
        None,
        description="Restrict to these candidate_ids; repeat query param.",
    ),
    final_rating_min: int | None = Query(
        None, description="final_rating >= this (inclusive)."
    ),
    final_rating_max: int | None = Query(
        None, description="final_rating <= this (inclusive)."
    ),
    final_verdict: list[str] | None = Query(
        None,
        description="Exact match on final_verdict; repeat param for multiple values.",
    ),
    limit: int | None = Query(
        default=None,
        description="Omit for no row cap (all matching rows). If set, 1–10000.",
    ),
    offset: int = Query(0, ge=0, description="Rows to skip."),
):
    """Filter `candidate_eval` (same query params as before). Response ``rows`` match GET /candidates: one row per distinct candidate in the result, with ``all_evaluations`` (full list per candidate)."""
    if limit is not None and (limit < 1 or limit > 10000):
        raise HTTPException(
            status_code=422,
            detail="limit must be between 1 and 10000, or omitted for no cap.",
        )
    ev_id = _parse_uuid_opt(evaluation_id, "evaluation_id")
    cid_one = _parse_uuid_opt(candidate_id, "candidate_id")
    jd_u = _parse_uuid_opt(jd_id, "jd_id")
    cids = None
    if candidate_ids:
        cids = [_parse_uuid(x, "candidate_ids") for x in candidate_ids]
    verdicts = _nonempty_str_list(final_verdict)
    try:
        rows = await db_manager.execute_function(
            _FN_RUN,
            2,
            ev_id,
            cid_one,
            jd_u,
            None,
            None,
            None,
            None,
            None,
            cids,
            final_rating_min,
            final_rating_max,
            verdicts,
            limit,
            offset,
        )
    except Exception as e:
        logger.exception("candidate_eval list: query failed")
        raise HTTPException(
            status_code=500, detail=f"Failed to list candidate evaluations: {e}"
        ) from e

    id_list: list[str] = []
    seen_ids: set[str] = set()
    for r in rows:
        cid = r.get("candidate_id")
        if cid is None:
            continue
        s = str(cid)
        if s not in seen_ids:
            seen_ids.add(s)
            id_list.append(s)

    cand_by_id: dict[str, dict[str, Any]] = {}
    eval_by_cid: dict[str, list[dict[str, Any]]] = {}
    if id_list:
        try:
            cand_by_id = await _fetch_candidates_by_ids(id_list)
            eval_by_cid = await _evaluations_by_candidate_ids(id_list)
        except Exception as e:
            logger.exception("candidate_eval list: load candidates failed")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load candidate info for evaluations: {e}",
            ) from e

    # One row per candidate (order = first appearance in filtered eval rows), same shape as GET /candidates.
    out_rows: list[dict[str, Any]] = []
    for cid_s in id_list:
        base = cand_by_id.get(cid_s)
        if base is None:
            continue
        out_rows.append(
            _candidate_row_as_list_endpoint(base, eval_by_cid.get(cid_s, []))
        )

    return BaseResponse(
        success=True,
        message="Candidate evaluations retrieved successfully.",
        data={
            "rows": jsonable_encoder(out_rows),
            "limit": limit,
            "offset": offset,
            "count": len(out_rows),
        },
    )


@router.get("", response_model=BaseResponse)
async def list_candidates(
    candidate_name: str | None = Query(
        None, description="Substring match (case-insensitive) on candidate_name."
    ),
    phone: str | None = Query(
        None, description="Substring match (case-insensitive) on phone."
    ),
    email: str | None = Query(
        None, description="Substring match (case-insensitive) on email."
    ),
    years_min: float | None = Query(
        None, description="Minimum years_of_experience (inclusive)."
    ),
    years_max: float | None = Query(
        None, description="Maximum years_of_experience (inclusive)."
    ),
    present_role: list[str] | None = Query(
        None,
        description="Exact match on present_role; repeat param for multiple values.",
    ),
    limit: int = Query(50, ge=1, le=500, description="Page size (max 500)."),
    offset: int = Query(0, ge=0, description="Rows to skip."),
):
    """List/filter candidates (candidate table only). Nested ``all_evaluations`` loaded separately."""
    present_roles = _nonempty_str_list(present_role)
    try:
        rows = await db_manager.execute_function(
            _FN_CANDIDATE,
            2,
            None,
            candidate_name,
            phone,
            email,
            None,
            None,
            None,
            years_min,
            years_max,
            present_roles,
            None,
            limit,
            offset,
        )
    except Exception as e:
        logger.exception("candidates list: query failed")
        raise HTTPException(
            status_code=500, detail=f"Failed to list candidates: {e}"
        ) from e

    ids = [str(r["candidate_id"]) for r in rows if r.get("candidate_id")]
    try:
        eval_by_cid = await _evaluations_by_candidate_ids(ids)
    except Exception as e:
        logger.exception("candidates list: load candidate_eval failed")
        raise HTTPException(
            status_code=500, detail=f"Failed to load evaluations for candidates: {e}"
        ) from e

    for r in rows:
        cid = str(r.get("candidate_id", ""))
        r["all_evaluations"] = eval_by_cid.get(cid, [])

    return BaseResponse(
        success=True,
        message="Candidates retrieved successfully.",
        data={
            "rows": jsonable_encoder(rows),
            "limit": limit,
            "offset": offset,
            "count": len(rows),
        },
    )


class CandidateIdsDeleteBody(BaseModel):
    """Delete candidates: one or many UUIDs (single delete: one element in the list)."""

    candidate_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Candidate UUIDs to delete (fn_candidates mode 3).",
    )


async def _delete_candidates_rows(
    candidate_ids: list[str],
) -> list[dict[str, Any]]:
    """Delete candidates by id; returns rows returned by DELETE ... RETURNING."""
    try:
        rows = await db_manager.execute_function(
            _FN_CANDIDATE,
            3,
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
            candidate_ids,
            None,
            None,
        )
    except Exception as e:
        logger.exception("candidates delete: DB failed")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete candidates: {e}"
        ) from e
    return [dict(r) for r in rows]


def _unlink_resume_if_safe(resume_path_val: Any) -> None:
    """Remove stored PDF under RESUME_FOLDER when basename-only path is valid."""
    if not resume_path_val or not str(resume_path_val).strip():
        return
    basename = Path(str(resume_path_val).strip()).name
    if basename != str(resume_path_val).strip():
        return
    file_path = (RESUME_FOLDER / basename).resolve()
    try:
        file_path.relative_to(RESUME_FOLDER.resolve())
    except ValueError:
        return
    try:
        if file_path.is_file():
            file_path.unlink()
    except OSError:
        logger.warning(
            "candidates delete: could not remove resume file %s",
            file_path,
            exc_info=True,
        )


@router.delete("", response_model=BaseResponse)
async def delete_candidates(body: CandidateIdsDeleteBody):
    """Delete candidates by UUID. JSON body: `{\"candidate_ids\": [\"...\"]}` (one or many).

    Related ``candidate_eval`` rows cascade. Resume PDFs removed when safe.
    If a single id was requested and it did not exist, returns 404.
    """
    seen: set[str] = set()
    parsed: list[str] = []
    for raw in body.candidate_ids:
        cid = _parse_uuid(raw, "candidate_ids")
        if cid not in seen:
            seen.add(cid)
            parsed.append(cid)

    rows = await _delete_candidates_rows(parsed)
    if len(parsed) == 1 and not rows:
        raise HTTPException(
            status_code=404,
            detail="Candidate not found for the given candidate_id.",
        )

    deleted_ids = {str(r.get("candidate_id")) for r in rows if r.get("candidate_id")}
    missing = [i for i in parsed if i not in deleted_ids]

    for row in rows:
        _unlink_resume_if_safe(row.get("resume_path"))

    return BaseResponse(
        success=True,
        message="Candidates deleted.",
        data={
            "requested_count": len(parsed),
            "deleted_count": len(rows),
            "deleted": jsonable_encoder(rows),
            "missing_candidate_ids": missing,
        },
    )


@router.post("", response_model=BaseResponse)
async def candidates_eval(
    jd_id: str = Form(..., description="Job description UUID."),
    file: UploadFile | None = File(
        None,
        description="Resume PDF/DOC/DOCX. Use with jd_id to create candidate + evaluation.",
    ),
    candidate_id: str | None = Form(
        None,
        description="Existing candidate_id from candidates; loads PDF from stored path.",
    ),
):
    has_file = file is not None and bool((file.filename or "").strip())
    cid_raw = (candidate_id or "").strip()

    if has_file and cid_raw:
        raise HTTPException(
            status_code=422,
            detail="Send either file (new candidate) or candidate_id (re-evaluate), not both.",
        )
    if not has_file and not cid_raw:
        raise HTTPException(
            status_code=422,
            detail="Provide file + jd_id, or candidate_id + jd_id.",
        )

    jd_row = await fetch_job_description_by_id(jd_id)
    if not jd_row:
        raise HTTPException(
            status_code=404,
            detail="Job description not found for the given jd_id.",
        )

    ctx_body = build_job_context_from_row(jd_row)
    if not ctx_body.strip():
        ctx_body = (
            "(No job description field values were available for the selected keys.)"
        )
    job_context = ctx_body
    jd_uuid = jd_row.get("jd_id")

    out: CandidatesEvalOutput
    evaluation_id = uuid.uuid4()

    if has_file:
        pdf_bytes = await normalize_upload_to_pdf_bytes(file)
        try:
            out = await _candidates_eval_pdf(
                pdf_bytes, job_context, prompt_dump_filename=_PROMPT_DUMP_UPLOAD
            )
        except Exception as e:
            logger.exception("candidates eval: Gemini failed (upload)")
            raise HTTPException(
                status_code=500, detail=f"Gemini evaluation failed: {e}"
            ) from e

        stem = (out.candidate_name or "").strip()
        if not stem:
            stem = Path(file.filename or "resume").stem or "resume"
        resume_basename = (f"{safe_resume_filename(stem)}_{uuid.uuid4()}.pdf").lower()
        try:
            save_resume_pdf(pdf_bytes, resume_basename)
        except Exception as e:
            logger.exception("candidates eval: file save failed")
            raise HTTPException(status_code=500, detail=f"File save failed: {e}") from e

        new_candidate_id = uuid.uuid4()
        try:
            cand_rows = await db_manager.execute_function(
                _FN_CANDIDATE,
                1,
                str(new_candidate_id),
                out.candidate_name,
                out.phone,
                out.email,
                out.years_of_experience,
                out.present_role,
                resume_basename,
                *_FN_CAND_TAIL6,
            )
        except Exception as e:
            logger.exception("candidates eval: candidate insert failed")
            raise HTTPException(
                status_code=500, detail=f"DB insert (candidate) failed: {e}"
            ) from e

        if not cand_rows:
            raise HTTPException(
                status_code=500, detail="Candidate insert returned no rows."
            )

        run_rows = await _insert_evaluation_run(
            evaluation_id,
            str(new_candidate_id),
            jd_uuid,
            out,
            _jd_title_for_eval_row(jd_row),
        )

        return BaseResponse(
            success=True,
            message="Candidate and requirements-aligned evaluation stored successfully.",
            data={
                "candidate_id": str(new_candidate_id),
                "evaluation_id": str(evaluation_id),
                "resume_path": resume_basename,
                "candidate_row": jsonable_encoder(dict(cand_rows[0])),
                "evaluation_row": jsonable_encoder(
                    _evaluation_row_for_response(dict(run_rows[0]))
                ),
            },
        )

    # candidate_id + jd_id: load PDF from stored path
    cand_uuid = _parse_uuid(cid_raw, "candidate_id")
    row = await _fetch_candidate_row(cand_uuid)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Candidate not found for the given candidate_id.",
        )

    rp = row.get("resume_path")
    if not rp or not str(rp).strip():
        raise HTTPException(
            status_code=422,
            detail="Candidate has no resume_path; cannot load PDF for re-evaluation.",
        )

    basename = Path(str(rp).strip()).name
    if basename != str(rp).strip():
        raise HTTPException(
            status_code=422, detail="Invalid resume_path on candidate row."
        )

    file_path = (RESUME_FOLDER / basename).resolve()
    try:
        file_path.relative_to(RESUME_FOLDER.resolve())
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Invalid resume file path.") from e
    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Resume file not found on disk: {basename}",
        )

    pdf_bytes = file_path.read_bytes()
    try:
        out = await _candidates_eval_pdf(
            pdf_bytes, job_context, prompt_dump_filename=_PROMPT_DUMP_REEVAL
        )
    except Exception as e:
        logger.exception("candidates eval: Gemini failed (existing candidate)")
        raise HTTPException(
            status_code=500, detail=f"Gemini evaluation failed: {e}"
        ) from e

    run_rows = await _insert_evaluation_run(
        evaluation_id,
        str(cand_uuid),
        jd_uuid,
        out,
        _jd_title_for_eval_row(jd_row),
    )

    return BaseResponse(
        success=True,
        message="Requirements-aligned evaluation stored successfully.",
        data={
            "candidate_id": cand_uuid,
            "evaluation_id": str(evaluation_id),
            "resume_path": basename,
            "evaluation_row": jsonable_encoder(
                _evaluation_row_for_response(dict(run_rows[0]))
            ),
        },
    )
