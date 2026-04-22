"""Resume info: list (GET), extract PDF and store (POST)."""

from __future__ import annotations

import io
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder

from src.api.v1.endpoints.llm_gemini import run_extraction
from src.db.manager import db_manager
from src.schemas.common import BaseResponse
from src.schemas.resume import DeleteResumeInfoBody, ResumeInfo

logger = logging.getLogger(__name__)

router = APIRouter()

_FN = "public.fn_resume_info"
RESUME_FOLDER = Path("resume")


def resume_path_for_db_from_basename(basename: str) -> str:
    """Absolute path string for DB after saving under ``RESUME_FOLDER / basename``."""
    raw = str(basename).strip()
    if not raw or Path(raw).name != raw:
        raise ValueError("resume_path must be a single filename (no directories).")
    return str((RESUME_FOLDER / raw).resolve())


def resolve_stored_resume_file(resume_path_val: Any) -> Path | None:
    """Resolve DB ``resume_path`` to a file under ``RESUME_FOLDER`` (absolute or legacy basename)."""
    if resume_path_val is None or not str(resume_path_val).strip():
        return None
    raw = str(resume_path_val).strip()
    p = Path(raw).expanduser()
    if p.is_absolute():
        candidate = p.resolve()
    else:
        candidate = (RESUME_FOLDER / Path(raw).name).resolve()
    try:
        candidate.relative_to(RESUME_FOLDER.resolve())
    except ValueError:
        return None
    return candidate


# 5 MB is generous for a resume PDF; 10 MB hard cap
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/msword",  # .doc
    # browsers sometimes send these for docx:
    "application/zip",
    "application/octet-stream",
}
_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}


def safe_resume_filename(name: str) -> str:
    """Normalize candidate name for use in a filename."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip())


def save_resume_pdf(pdf_bytes: bytes, resume_path: str) -> None:
    RESUME_FOLDER.mkdir(exist_ok=True)
    (RESUME_FOLDER / resume_path).write_bytes(pdf_bytes)


def _convert_docx_to_pdf_bytes(docx_bytes: bytes) -> bytes:
    """
    Convert .doc / .docx bytes to PDF bytes.

    Uses mammoth to extract plain text from the Word document, then
    builds a clean single-column PDF with fpdf2.  Formatting is not
    preserved (bold, tables, etc.) but the text content is — which is
    all Gemini needs for resume extraction.
    """
    try:
        import mammoth
    except ImportError as exc:
        raise RuntimeError(
            "mammoth is required to convert Word documents. "
            "Install it with: pip install mammoth"
        ) from exc
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError(
            "fpdf2 is required to convert Word documents to PDF. "
            "Install it with: pip install fpdf2"
        ) from exc

    result = mammoth.extract_raw_text(io.BytesIO(docx_bytes))
    text = result.value.strip() or "(No readable text found in document.)"

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)

    for line in text.splitlines():
        # multi_cell wraps long lines automatically
        safe_line = line.encode("latin-1", errors="replace").decode("latin-1")
        pdf.multi_cell(0, 6, safe_line)

    return bytes(pdf.output())


async def normalize_upload_to_pdf_bytes(file: UploadFile) -> bytes:
    """
    Read the uploaded file, enforce size and type rules, then return
    PDF bytes regardless of whether the input was a PDF or Word doc.

    Accepted inputs:
      • PDF  → returned as-is.
      • .docx / .doc → text extracted with mammoth, re-encoded as PDF.

    Raises HTTPException 413 when the file exceeds MAX_UPLOAD_BYTES.
    Raises HTTPException 415 for unsupported file types.
    """
    import filetype as _filetype

    raw: bytes = await file.read()
    await file.close()

    # ── Size check ─────────────────────────────────────────────────────
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({len(raw) / (1024 * 1024):.1f} MB). "
                f"Maximum allowed size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )

    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Type detection (magic bytes first, filename/mime as fallback) ──
    kind = _filetype.guess(raw)
    mime = (kind.mime if kind else "").lower()
    ext = (
        Path(file.filename or "").suffix.lower()
        if file.filename
        else ""
    )

    is_pdf = mime == "application/pdf" or raw[:4] == b"%PDF"
    is_word = mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",  # docx are ZIP archives; filetype may report this
    ) or ext in (".docx", ".doc")

    if is_pdf:
        return raw

    if is_word:
        try:
            logger.info("normalize_upload: converting Word document to PDF (ext=%s)", ext or mime)
            return _convert_docx_to_pdf_bytes(raw)
        except Exception as exc:
            logger.exception("normalize_upload: Word-to-PDF conversion failed")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to convert Word document to PDF: {exc}",
            ) from exc

    # Unknown / unsupported
    raise HTTPException(
        status_code=415,
        detail=(
            f"Unsupported file type (detected: '{mime or ext or 'unknown'}')."
            " Please upload a PDF, .docx, or .doc file."
        ),
    )


async def read_upload_bytes(file: UploadFile) -> bytes:
    """Raw read helper (no validation). Prefer normalize_upload_to_pdf_bytes for uploads."""
    try:
        return await file.read()
    finally:
        await file.close()


async def insert_resume_info(
    resume_uuid: uuid.UUID, info: ResumeInfo, resume_path: str
) -> dict:
    rows = await db_manager.execute_function(
        _FN,
        1,
        str(resume_uuid),
        None,
        0,
        info.name,
        info.email,
        info.phone,
        info.location,
        info.linkedin,
        info.summary,
        info.total_experience_years,
        info.current_role,
        info.skills,
        [e.model_dump(mode="json") for e in info.experience],
        [e.model_dump(mode="json") for e in info.education],
        [p.model_dump(mode="json") for p in info.projects] if info.projects else None,
        list(info.certifications) if info.certifications else None,
        list(info.languages) if info.languages else None,
        False,
        resume_path,
        None,
        None,
        None,
        None,
        None,
    )
    if not rows:
        raise RuntimeError("fn_resume_info insert returned no rows — DB constraint may have rejected the insert.")
    return rows[0]


def _skills_arg(skills_json: str | None) -> Any:
    if not skills_json or not skills_json.strip():
        return None
    try:
        parsed = json.loads(skills_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422, detail=f"skills must be valid JSON: {e}"
        ) from e
    if not isinstance(parsed, (list, dict)):
        raise HTTPException(
            status_code=422, detail="skills JSON must be an array or object"
        )
    return parsed


async def fetch_resume_info_by_resume_ids(
    resume_ids: list[str],
) -> list[dict[str, Any]]:
    """fn_resume_info mode 2: rows matching p_resume_ids only (no other filters)."""
    if not resume_ids:
        return []
    try:
        rows = await db_manager.execute_function(
            _FN,
            2,
            None,
            None,
            0,
            *([None] * 18),
            resume_ids,
            None,
            None,
        )
        return rows
    except Exception:
        logger.exception("fetch_resume_info_by_resume_ids failed")
        raise


@router.get("", response_model=BaseResponse)
async def list_resume_info(
    resume_id: UUID | None = Query(
        default=None,
        description="Exact resume_id (sent to DB as a single-element id list).",
    ),
    candidate_name: str | None = Query(default=None),
    email: str | None = Query(default=None),
    phone: str | None = Query(default=None),
    location: str | None = Query(default=None),
    linkedin: str | None = Query(default=None),
    total_experience_years: float | None = Query(default=None),
    min_experience: float | None = Query(default=None),
    max_experience: float | None = Query(default=None),
    skills: str | None = Query(
        default=None,
        description='JSON array for skills containment, e.g. ["Python"].',
    ),
    evaluated: bool | None = Query(default=None),
    created_from: datetime | None = Query(
        default=None, description="Filter ri.created_at >= this (inclusive)."
    ),
    created_to: datetime | None = Query(
        default=None, description="Filter ri.created_at <= this (inclusive)."
    ),
    limit: int | None = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List or filter resume_info rows (fn_resume_info mode 2)."""
    resume_ids_arg = [str(resume_id)] if resume_id else None
    try:
        rows = await db_manager.execute_function(
            _FN,
            2,
            None,
            limit,
            offset,
            candidate_name,
            email,
            phone,
            location,
            linkedin,
            None,
            total_experience_years,
            None,
            _skills_arg(skills),
            None,
            None,
            None,
            None,
            None,
            evaluated,
            None,
            min_experience,
            max_experience,
            resume_ids_arg,
            created_from,
            created_to,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("resume-info GET failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    items: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        item["evaluations"] = []
        items.append(jsonable_encoder(item))

    return BaseResponse(
        message="Resume info retrieved successfully.",
        data={
            "count": len(rows),
            "items": items,
        },
    )


@router.delete("", response_model=BaseResponse)
async def delete_resume_info(body: DeleteResumeInfoBody):
    """Bulk-delete resume_info rows by resume_id (fn_resume_info mode 4)."""
    ids = [str(x) for x in body.resume_ids]
    try:
        rows = await db_manager.execute_function(
            _FN,
            4,
            None,
            None,
            0,
            *([None] * 14),
            None,
            None,
            None,
            None,
            ids,
            None,
            None,
        )
    except Exception as e:
        logger.warning("resume-info DELETE failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    encoded = jsonable_encoder(rows)
    return BaseResponse(
        message="Resume info deleted successfully.",
        data={
            "count": len(rows),
            "deleted": encoded,
        },
    )


@router.post("/extract", response_model=BaseResponse)
async def extract_resume(
    file: UploadFile = File(...),
    jd_id: str = Form(...),
):
    """Extract resume from PDF/Word doc, save file, insert resume_info (jd_id reserved for future use)."""
    pdf_bytes = await normalize_upload_to_pdf_bytes(file)

    try:
        info = await run_extraction(pdf_bytes)
    except Exception as e:
        logger.warning("resume-info/extract: extraction failed: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Gemini extraction failed: {e}"
        ) from e

    resume_uuid = uuid.uuid4()
    resume_path = f"{safe_resume_filename(info.name)}_{resume_uuid}.pdf"

    try:
        save_resume_pdf(pdf_bytes, resume_path)
    except Exception as e:
        logger.warning("resume-info/extract: file save failed: %s", e)
        raise HTTPException(status_code=500, detail=f"File save failed: {e}") from e

    try:
        resume_path_db = resume_path_for_db_from_basename(resume_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        row = await insert_resume_info(resume_uuid, info, resume_path_db)
    except Exception as e:
        logger.warning("resume-info/extract: db insert failed: %s", e)
        raise HTTPException(status_code=500, detail=f"DB insert failed: {e}") from e

    logger.info("resume-info/extract: db inserted resume_info id=%s", row["resume_id"])
    logger.info(
        "resume-info/extract: done resume_id=%s path=%s",
        row["resume_id"],
        resume_path,
    )
    return BaseResponse(
        success=True,
        message="Resume extracted and stored successfully.",
        data={
            "resume_id": str(row["resume_id"]),
            "resume_path": resume_path_db,
            "extracted_data": info.model_dump(mode="json"),
        },
    )
