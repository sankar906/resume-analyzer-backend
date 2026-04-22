"""Load job_description rows via public.fn_job_description (shared by candidates, resume_job_match, etc.)."""

from __future__ import annotations

import uuid
from typing import Any

from src.db.manager import db_manager


def parse_jd_uuid(jd_id: str) -> str | None:
    try:
        return str(uuid.UUID(jd_id.strip()))
    except (ValueError, AttributeError):
        return None


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
