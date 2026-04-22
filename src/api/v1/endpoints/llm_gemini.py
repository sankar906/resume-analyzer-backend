"""Google Gemini helpers for resume extraction and evaluation (no HTTP routes)."""

import asyncio
import json
import logging
from typing import Any, Callable

from google import genai
from google.genai import types
from pydantic import ValidationError

from src.api.v1.prompts.eval_injection import (
    build_job_context_from_row,
    filter_resume_json_for_prompt,
)
from src.api.v1.prompts.gemini_prompt import (
    CANDIDATES_EVAL_PROMPT,
    EVALUATE_PROMPT,
    JOB_MATCH_PROMPT_MULTI,
    JOB_MATCH_PROMPT_SINGLE,
    RESUME_PARSING_PROMPT,
)
from src.core.config import get_settings
from src.schemas.candidates_eval import CandidatesEvalOutput
from src.schemas.resume import EvaluationOutput, ResumeInfo, ResumeJobMatchOutput

logger = logging.getLogger(__name__)


def _parse_json_with_one_llm_retry(
    *,
    label: str,
    parse: Callable[[str], Any],
    generate_response: Callable[[], Any],
) -> Any:
    """If ``parse(response.text)`` fails, call ``generate_response`` once more and parse again."""
    response = generate_response()
    try:
        return parse(response.text)
    except (ValidationError, json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("%s: output parse failed (%s); retrying generate_content once", label, e)
        response = generate_response()
        return parse(response.text)


def _extract(pdf_bytes: bytes) -> ResumeInfo:
    try:
        settings = get_settings()
        client = genai.Client(api_key=settings.google_api_key)

        def _generate():
            try:
                return client.models.generate_content(
                    model=settings.gemini_model,
                    contents=[
                        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                        types.Part.from_text(text=RESUME_PARSING_PROMPT),
                    ],
                    config=types.GenerateContentConfig(
                        temperature=settings.gemini_temperature,
                        response_mime_type="application/json",
                        response_schema=ResumeInfo,
                    ),
                )
            except Exception:
                logger.exception("gemini extraction: generate_content failed")
                raise

        return _parse_json_with_one_llm_retry(
            label="gemini extraction",
            parse=ResumeInfo.model_validate_json,
            generate_response=_generate,
        )
    except Exception:
        logger.exception("gemini extraction failed")
        raise


def _evaluate(
    resume_json: str,
    jd_row: dict[str, Any] | None = None,
) -> EvaluationOutput:
    try:
        settings = get_settings()
        client = genai.Client(api_key=settings.google_api_key)

        resume_for_prompt = filter_resume_json_for_prompt(resume_json)

        if jd_row:
            ctx_body = build_job_context_from_row(jd_row)
            if not ctx_body.strip():
                ctx_body = "(No job description field values were available for the selected keys.)"
            job_context = "\n" + ctx_body
        else:
            job_context = "(No job description was provided.)"

        prompt = EVALUATE_PROMPT.format(
            job_context=job_context,
            resume_text=resume_for_prompt,
        )
        try:
            with open("prompt.txt", "w", encoding="utf-8") as f:
                f.write(prompt)
        except OSError:
            logger.warning("llm_gemini: could not write prompt.txt", exc_info=True)

        def _generate():
            try:
                return client.models.generate_content(
                    model=settings.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=settings.gemini_temperature,
                        response_mime_type="application/json",
                        response_schema=EvaluationOutput,
                    ),
                )
            except Exception:
                logger.exception("gemini evaluation: generate_content failed")
                raise

        return _parse_json_with_one_llm_retry(
            label="gemini evaluation",
            parse=EvaluationOutput.model_validate_json,
            generate_response=_generate,
        )
    except Exception:
        logger.exception("gemini evaluation failed")
        raise


def _resume_job_match_pdf(pdf_bytes: bytes, prompt: str) -> ResumeJobMatchOutput:
    try:
        settings = get_settings()
        client = genai.Client(api_key=settings.google_api_key)

        def _generate():
            try:
                return client.models.generate_content(
                    model=settings.gemini_model,
                    contents=[
                        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                        types.Part.from_text(text=prompt),
                    ],
                    config=types.GenerateContentConfig(
                        temperature=settings.gemini_temperature,
                        response_mime_type="application/json",
                        response_schema=ResumeJobMatchOutput,
                    ),
                )
            except Exception:
                logger.exception("gemini resume job match: generate_content failed")
                raise

        return _parse_json_with_one_llm_retry(
            label="gemini resume job match",
            parse=ResumeJobMatchOutput.model_validate_json,
            generate_response=_generate,
        )
    except Exception:
        logger.exception("gemini resume job match failed")
        raise


def _candidates_eval_llm_pdf(
    pdf_bytes: bytes, prompt: str
) -> CandidatesEvalOutput:
    """Job context + PDF resume → candidates eval JSON (no strict response_schema; dict keys are dynamic)."""
    try:
        settings = get_settings()
        client = genai.Client(api_key=settings.google_api_key)

        def _generate():
            try:
                return client.models.generate_content(
                    model=settings.gemini_model,
                    contents=[
                        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                        types.Part.from_text(text=prompt),
                    ],
                    config=types.GenerateContentConfig(
                        temperature=settings.gemini_temperature,
                        response_mime_type="application/json",
                    ),
                )
            except Exception:
                logger.exception("gemini candidates eval: generate_content failed")
                raise

        return _parse_json_with_one_llm_retry(
            label="gemini candidates eval",
            parse=CandidatesEvalOutput.model_validate_json,
            generate_response=_generate,
        )
    except Exception:
        logger.exception("gemini candidates eval (pdf) failed")
        raise


def build_candidates_eval_prompt(
    job_context: str,
    resume_instruction: str,
) -> str:
    """Fill CANDIDATES_EVAL_PROMPT."""
    return CANDIDATES_EVAL_PROMPT.format(
        job_context=job_context,
        resume_instruction=resume_instruction,
    )


def build_job_match_prompt(
    *,
    single_job: bool,
    allowed_titles: list[str],
    job_contexts: str,
) -> str:
    """Fill JOB_MATCH_PROMPT_SINGLE or MULTI with titles block and job text."""
    block = "\n".join(f"- {t}" for t in allowed_titles)
    if single_job:
        return JOB_MATCH_PROMPT_SINGLE.format(
            allowed_titles_block=block,
            job_contexts=job_contexts,
        )
    return JOB_MATCH_PROMPT_MULTI.format(
        allowed_titles_block=block,
        job_contexts=job_contexts,
    )


async def run_resume_job_match_pdf(
    pdf_bytes: bytes, prompt: str
) -> ResumeJobMatchOutput:
    return await asyncio.to_thread(_resume_job_match_pdf, pdf_bytes, prompt)


async def run_extraction(pdf_bytes: bytes) -> ResumeInfo:
    return await asyncio.to_thread(_extract, pdf_bytes)


async def run_evaluation(
    resume_json: str,
    jd_row: dict[str, Any] | None = None,
) -> EvaluationOutput:
    return await asyncio.to_thread(_evaluate, resume_json, jd_row)


async def run_candidates_eval_pdf(
    pdf_bytes: bytes, prompt: str
) -> CandidatesEvalOutput:
    return await asyncio.to_thread(_candidates_eval_llm_pdf, pdf_bytes, prompt)
