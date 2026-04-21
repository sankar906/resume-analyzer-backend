"""Build job-context and resume text for evaluation prompts from DB rows / JSON."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Which job_description columns go into the LLM prompt. Empty list => no job text from this helper.
JD_PROMPT_FIELDS: list[str] = ["title", "description", "requirements"]

# Structured job requirements: section keys to omit from the prompt (e.g. "attitude_mindset").
JD_REQUIREMENTS_SECTION_BLACKLIST: list[str] = ["attitude_mindset"]

# Which resume JSON keys to send; empty => full resume dict as readable text.
RESUME_PROMPT_FIELDS: list[str] = [
    "summary",
    "total_experience_years",
    "skills",
    "experience",
    "education",
    "projects",
    "certifications",
]

# Top-level resume keys to omit after field selection (e.g. "certifications").
RESUME_PROMPT_BLACKLIST: list[str] = []


def _is_scalar(x: Any) -> bool:
    return x is None or isinstance(x, (str, int, float, bool))


def _scalar_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, bool):
        return "true" if x else "false"
    return str(x)


# Job requirements JSON: preferred section order for known keys. Subject/level/rising lists render as
# markdown tables in prompts; nested dict/list uses indented text. Add optional entries here only to
# override the default label (snake_case -> Title Case).
_REQ_SECTION_ORDER = (
    "technical_skills",
    "core_competencies",
    "attitude_mindset",
)
_REQ_SECTION_LABEL = {
    "technical_skills": "Technical skills",
    "core_competencies": "Core competencies",
    "attitude_mindset": "Attitude & mindset",
}


def _jd_requirements_blacklist() -> set[str]:
    return {k.strip() for k in JD_REQUIREMENTS_SECTION_BLACKLIST if k.strip()}


def _skill_item_line(d: dict[str, Any]) -> str:
    """One line per subject/level/rising row."""
    subj = str(d.get("subject", "")).strip()
    lv = d.get("level")
    rising = d.get("rising")
    bits: list[str] = []
    if lv is not None and str(lv).strip():
        bits.append(str(lv).strip())
    if rising is True:
        bits.append("rising")
    elif rising is False:
        bits.append("stable")
    if bits and subj:
        return f"{subj} ({', '.join(bits)})"
    return subj


def _is_subject_skill_dict(x: Any) -> bool:
    return isinstance(x, dict) and "subject" in x


def _format_list_of_skill_dicts(items: list[Any], pad: str) -> str:
    lines: list[str] = []
    for x in items:
        if _is_subject_skill_dict(x):
            lines.append(f"{pad}- {_skill_item_line(x)}")
        elif isinstance(x, dict):
            lines.append(
                f"{pad}- {_format_structured_as_text(x, 0).replace(chr(10), ' ')}"
            )
        else:
            lines.append(f"{pad}- {_scalar_text(x)}")
    return "\n".join(lines)


def _markdown_table_cell(value: Any) -> str:
    """Single table cell: no raw pipe characters."""
    if value is None:
        return ""
    s = (
        str(value).strip()
        if not isinstance(value, bool)
        else ("true" if value else "false")
    )
    return s.replace("|", " ")


def _format_skill_dicts_as_markdown_table(items: list[Any], line_prefix: str) -> str:
    """Markdown table for job requirement sections (subject / level / rising).

    First column header is ``skills`` (not the section title) so we do not repeat e.g. "Technical skills"
    next to the section line ``Technical skills:``.
    """
    out: list[str] = [
        f"{line_prefix}| skills | Level | Rising |",
        f"{line_prefix}| --- | --- | --- |",
    ]
    for x in items:
        if not isinstance(x, dict):
            continue
        subj = _markdown_table_cell(x.get("subject", ""))
        lv_raw = x.get("level")
        lv = _markdown_table_cell(lv_raw) if lv_raw is not None else ""
        rising_raw = x.get("rising")
        if rising_raw is None:
            r_cell = ""
        elif isinstance(rising_raw, bool):
            r_cell = "true" if rising_raw else "false"
        else:
            r_cell = _markdown_table_cell(rising_raw)
        out.append(f"{line_prefix}| {subj} | {lv} | {r_cell} |")
    return "\n".join(out)


def _requirement_section_label(key: str) -> str:
    return _REQ_SECTION_LABEL.get(key, str(key).replace("_", " ").title())


def _requirements_section_keys(d: dict[str, Any], bl: set[str]) -> list[str]:
    """Known sections first (in _REQ_SECTION_ORDER), then any other keys (sorted, stable)."""
    out: list[str] = []
    seen: set[str] = set()
    for key in _REQ_SECTION_ORDER:
        if key in bl or key not in d:
            continue
        out.append(key)
        seen.add(key)
    rest = sorted(k for k in d if k not in seen and k not in bl)
    return out + rest


def _append_one_requirement_section(
    lines: list[str],
    pad: str,
    key: str,
    v: Any,
    indent: int,
) -> None:
    """Same formatting for built-in and new requirement sections."""
    lines.append(f"{pad}{_requirement_section_label(key)}:")
    if isinstance(v, list) and v and all(_is_subject_skill_dict(x) for x in v):
        lines.append(_format_skill_dicts_as_markdown_table(v, pad + "  "))
    elif isinstance(v, (dict, list)):
        inner = _format_structured_as_text(v, indent + 1)
        if inner:
            lines.append(inner)
    else:
        lines.append(f"{pad}  {_scalar_text(v)}")


def _format_requirements_dict(d: dict[str, Any], indent: int = 0) -> str:
    """Readable multi-section requirements; new top-level keys use the same rules as known ones."""
    pad = "  " * indent
    lines: list[str] = []
    bl = _jd_requirements_blacklist()
    for key in _requirements_section_keys(d, bl):
        _append_one_requirement_section(lines, pad, key, d[key], indent)
    return "\n".join(lines)


def _looks_like_jd_requirements(obj: Any) -> bool:
    """True if this dict is structured like job requirements (including only new section keys)."""
    if not isinstance(obj, dict) or not obj:
        return False
    if any(k in obj for k in _REQ_SECTION_LABEL):
        return True
    for v in obj.values():
        if isinstance(v, list) and v and all(_is_subject_skill_dict(x) for x in v):
            return True
    if all(isinstance(v, (list, dict)) for v in obj.values()):
        return True
    return False


def _format_structured_as_text(val: Any, indent: int = 0) -> str:
    """Recursively turn dict/list/scalar trees into indented text (one newline between siblings)."""
    pad = "  " * indent
    if val is None:
        return ""
    if _is_scalar(val):
        return f"{pad}{_scalar_text(val)}"

    if isinstance(val, list):
        if not val:
            return ""
        if all(_is_scalar(x) for x in val):
            return ", ".join(_scalar_text(x) for x in val if x is not None)
        if all(_is_subject_skill_dict(x) for x in val):
            return _format_list_of_skill_dicts(val, pad)
        # Multiple resume-style records (jobs, degrees, projects): numbered blocks + blank line between
        if all(isinstance(x, dict) for x in val) and not all(
            _is_subject_skill_dict(x) for x in val
        ):
            blocks: list[str] = []
            for i, item in enumerate(val, start=1):
                inner = _format_structured_as_text(item, indent + 1)
                if not inner.strip():
                    continue
                blocks.append(f"{pad}[{i}]\n{inner}")
            return "\n".join(blocks)
        parts = [_format_structured_as_text(x, indent + 1) for x in val]
        parts = [p for p in parts if p]
        return "\n".join(parts)

    if isinstance(val, dict):
        if _looks_like_jd_requirements(val) and indent == 0:
            return _format_requirements_dict(val, indent)
        parts: list[str] = []
        for k, v in val.items():
            key = str(k)
            if _is_scalar(v) or v is None:
                if v is None:
                    parts.append(f"{pad}{key}:")
                else:
                    parts.append(f"{pad}{key}: {_scalar_text(v)}")
            elif isinstance(v, list):
                if not v:
                    continue
                if all(_is_scalar(x) for x in v):
                    joined = ", ".join(_scalar_text(x) for x in v if x is not None)
                    parts.append(f"{pad}{key}: {joined}")
                elif all(_is_subject_skill_dict(x) for x in v):
                    parts.append(f"{pad}{key}:")
                    parts.append(_format_list_of_skill_dicts(v, pad + "  "))
                else:
                    inner = _format_structured_as_text(v, indent + 1)
                    parts.append(f"{pad}{key}:\n{inner}" if inner else f"{pad}{key}:")
            elif isinstance(v, dict):
                inner = _format_structured_as_text(v, indent + 1)
                parts.append(f"{pad}{key}:\n{inner}" if inner else f"{pad}{key}:")
        return "\n".join(parts)

    return f"{pad}{val}"


def _deep_unwrap_json_strings(obj: Any) -> Any:
    """Parse string values that hold JSON so nested structures unpack correctly."""
    if isinstance(obj, dict):
        return {k: _deep_unwrap_json_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_unwrap_json_strings(x) for x in obj]
    if isinstance(obj, str):
        s = obj.strip()
        if len(s) >= 2 and s[0] in "{[" and s[-1] in "}]":
            try:
                inner = json.loads(s)
                return _deep_unwrap_json_strings(inner)
            except json.JSONDecodeError:
                pass
        return obj
    return obj


def _coerce_to_json_tree(val: Any) -> Any:
    """Turn a DB cell into dict/list when it is JSON text or already structured."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return _deep_unwrap_json_strings(val)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if (s.startswith("{") and s.endswith("}")) or (
            s.startswith("[") and s.endswith("]")
        ):
            try:
                parsed = json.loads(s)
                return _deep_unwrap_json_strings(parsed)
            except json.JSONDecodeError:
                pass
        return s
    return val


def _jd_cell_to_prompt_text(val: Any) -> tuple[str, bool]:
    """(text, is_structured). Plain prose vs dict/list rendered as indented text."""
    if val is None:
        return "", False
    coerced = _coerce_to_json_tree(val)
    if isinstance(coerced, dict) and _looks_like_jd_requirements(coerced):
        return _format_requirements_dict(coerced), True
    if isinstance(coerced, (dict, list)):
        return _format_structured_as_text(coerced), True
    if isinstance(coerced, str):
        return coerced, False
    return _scalar_text(coerced), False


def _indent_block(text: str, prefix: str = "  ") -> str:
    if not text.strip():
        return text
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def _normalize_jd_fields(requested: list[str] | None) -> list[str]:
    if not requested:
        return []
    return [k.strip() for k in requested if k.strip()]


def _normalize_resume_fields(requested: list[str] | None) -> list[str] | None:
    """None or empty list => include all keys from the resume dict."""
    if not requested:
        return None
    out = [k.strip() for k in requested if k.strip()]
    return out if out else None


def _resume_prompt_blacklist() -> set[str]:
    return {k.strip() for k in RESUME_PROMPT_BLACKLIST if k.strip()}


def build_job_context_from_row(row: dict[str, Any]) -> str:
    """Human-readable block from job_description row using JD_PROMPT_FIELDS."""
    try:
        effective = JD_PROMPT_FIELDS if JD_PROMPT_FIELDS else None
        fields = _normalize_jd_fields(effective)
        if not fields:
            return ""

        lines: list[str] = []
        label_map = {
            "title": "Job Title",
            "description": "Job description",
            "requirements": "Requirements",
            "responsibilities": "Responsibilities",
            "department": "Department",
            "location": "Location",
            "status": "Status",
            "min_experience": "Min experience (years)",
            "max_experience": "Max experience (years)",
            "min_salary": "Min salary",
            "max_salary": "Max salary",
            "employment_type": "Employment type",
            "remote_allowed": "Remote allowed",
            "openings": "Openings",
            "level": "Level",
            "hiring_manager": "Hiring manager",
            "reporting_to": "Reporting to",
        }

        for key in fields:
            val = row.get(key)
            if val is None or val == "":
                continue
            label = label_map.get(key, key.replace("_", " ").title())
            text, structured = _jd_cell_to_prompt_text(val)
            if not text.strip():
                continue
            if structured or "\n" in text:
                lines.append(f"{label}:\n{_indent_block(text)}")
            else:
                lines.append(f"{label}: {text}")

        if not lines:
            return ""
        return "\n".join(lines)
    except Exception:
        logger.warning("build_job_context_from_row failed", exc_info=True)
        return ""


def filter_resume_json_for_prompt(resume_json: str) -> str:
    """Subset resume JSON using RESUME_PROMPT_FIELDS; empty => full resume. Readable text, not JSON."""
    try:
        effective = RESUME_PROMPT_FIELDS if RESUME_PROMPT_FIELDS else None
        subset = _normalize_resume_fields(effective)
        try:
            data = json.loads(resume_json)
        except json.JSONDecodeError:
            return resume_json
        if not isinstance(data, dict):
            return resume_json
        if subset is None:
            payload: dict[str, Any] = data
        else:
            keys: list[str] = list(subset)
            payload = {k: data[k] for k in keys if k in data}
        payload = _deep_unwrap_json_strings(payload)
        bl = _resume_prompt_blacklist()
        if bl:
            payload = {k: v for k, v in payload.items() if k not in bl}
        return _format_structured_as_text(payload)
    except Exception:
        logger.warning("filter_resume_json_for_prompt failed", exc_info=True)
        return resume_json
