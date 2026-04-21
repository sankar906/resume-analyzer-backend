# SeaHire — Resume Evaluation API

FastAPI service that stores job descriptions and candidate resumes in **PostgreSQL** (via SQL functions), runs **Google Gemini** for PDF extraction, resume–job **matching**, and resume–job **evaluation**, and persists structured data in the database.

## Business goal

Recruiters and hiring workflows need a **repeatable way** to:

1. **Store** open roles (**job descriptions**) and **candidates** (**resume_info**) in one system of record.
2. **Turn PDFs into structured data** (skills, experience, education) so they can be searched and reused.
3. **Match** a resume against one or more roles (**resume_job_match**) and record the preferred role and JD.
4. **Score a candidate against a specific job** with **consistent criteria** (knowledge areas, technical skills, experience, certifications, overall verdict).
5. **Keep an audit trail**: stored rows linked to `resume_id`, `jd_id`, and `match_id` where applicable.

The API is the backend for that pipeline: ingest → extract / match → evaluate → persist.

## Why it is built this way

### PostgreSQL functions (`fn_job_description`, `fn_resume_info`, `fn_resume_evaluation`, `fn_resume_job_match`)

The app does **not** hand-write `INSERT`/`UPDATE`/`SELECT` for every case. It calls **one function per domain** with a **mode** argument. That keeps **business rules and schema changes** in the database layer where data lives, and keeps the Python side thin: **call the function, map rows to JSON**.

### Gemini in `llm_gemini.py` and `asyncio.to_thread`

The **Google GenAI client used here is synchronous** (it blocks while waiting for the HTTP response). FastAPI handlers are **`async`** so the server can juggle many connections.

If we called Gemini **directly** inside `async def`, each long request would **block the asyncio event loop** and stall other requests on the same worker.

**`asyncio.to_thread(...)`** runs Gemini helpers in a **thread pool**. The event loop stays free for other work; **this request still waits** until Gemini returns. So: **correct behavior for the caller**, **better throughput** for everyone else.

### Prompt text (`eval_injection.py`)

Job and resume fields are formatted as **readable indented text** for the model, not raw JSON blobs, so the evaluator prompt stays clear and stable.

## How it runs

- **`main.py`** — FastAPI app, lifespan opens an **asyncpg** pool (`init_db`), mounts **`/api/v1`** (`src/api/v1/api.py`).
- **Config** — `src/core/config.py`: `.env` / env vars for Postgres (`DATABASE_URL` or `POSTGRES_*`), **`GOOGLE_API_KEY`**, **`GEMINI_MODEL`** (default `gemini-3-flash-preview`).
- **DB** — `src/db/manager.py` calls PostgreSQL **set-returning functions** with `SELECT * FROM schema.fn(...)`; arguments are encoded (JSON for JSONB, `uuid[]` where applicable).
- **Resume files on disk** — PDFs are stored under **`resume/`** (relative to the process working directory, usually the project root). The DB stores a relative **`resume_path`** string (filename under that folder).

Default dev server: `python main.py` → `http://127.0.0.1:8008`.

---

## Response envelope

Successful routes return **`BaseResponse`** (`src/schemas/common.py`):

| Field | Type | Description |
|--------|------|-------------|
| `success` | `boolean` | Typically `true` on success. |
| `message` | `string` | Human-readable status. |
| `data` | `object` \| `array` \| `null` | Endpoint-specific payload (see below). |

Validation errors often return **`422`** with `{"detail": ...}` (FastAPI). Other errors return **`4xx`/`5xx`** with `{"detail": "..."}` unless handled otherwise in `main.py`.

---

## API surface (`/api/v1`)

Base URL examples: `http://127.0.0.1:8008/api/v1/...`

| Area | Prefix | Role |
|------|--------|------|
| Job descriptions | `/job_description` | CRUD-style access via **`public.fn_job_description`**. |
| Resume info | `/resume-info` | Candidates: list, **`/extract`**, delete via **`public.fn_resume_info`**. |
| Resume evaluation | `/resume-evaluation` | Evaluations: list, filter, delete, **`/evaluate`**, **`/upload`** via **`public.fn_resume_evaluation`**. |
| Resume–job match | `/resume-job-match` | Match PDF to one or more JDs, list, delete, **`/promote`** via **`public.fn_resume_job_match`**. |

---

## Job descriptions

| Method | Path | Input | Output `data` (typical) |
|--------|------|--------|-------------------------|
| **GET** | `/job_description` | Query: optional `uuid=<jd_id>` | Job description row(s) in `data`. |
| **POST** | `/job_description` | JSON body: `JobDescriptionCreate` | Created row(s). |
| **PUT** | `/job_description/{job_uuid}` | Path: `job_uuid`; JSON: `JobDescriptionUpdate` | Updated row(s). |
| **DELETE** | `/job_description/{job_uuid}` | Path: `job_uuid` | Deletion result. |

---

## Resume info

| Method | Path | Input | Output `data` (typical) |
|--------|------|--------|-------------------------|
| **GET** | `/resume-info` | Query: filters (`resume_id`, `candidate_name`, `email`, `limit`, `offset`, …) | `{ "count", "rows": [...] }` (and evaluations where implemented). |
| **POST** | `/resume-info/extract` | **multipart/form-data**: `file` (PDF/DOC/DOCX), `jd_id` (string UUID, form field) | `{ "resume_id", "resume_path", "extracted_data": { ... ResumeInfo ... } }` |
| **DELETE** | `/resume-info` | JSON body: `{ "resume_ids": ["<uuid>", ...] }` (min 1) | `{ "count", "deleted": [...] }` — related **`resume_evaluation`** rows for those IDs are removed first. |

**Order of operations for `/resume-info/extract`:** normalize upload to PDF bytes → **Gemini extraction** → build filename from extracted name → **save PDF under `resume/`** → insert **`resume_info`**. If extraction fails, nothing is written to `resume/` and no row is inserted.

---

## Resume evaluation

| Method | Path | Input | Output `data` (typical) |
|--------|------|--------|-------------------------|
| **POST** | `/resume-evaluation/evaluate` | JSON: **`EvaluateRequest`** — `jd_id` (required), optional `resume_id`, optional `extracted_resume_json`, optional `resume_path` (see schema rules in `src/schemas/resume.py`) | `{ "evaluation_id", "evaluation": { ... EvaluationOutput ... } }` |
| **POST** | `/resume-evaluation/upload` | **multipart/form-data**: `file`, `jd_id` | Combined extract + evaluate; includes `extracted_data`, evaluation ids, etc. |
| **GET** | `/resume-evaluation` | Query: filters (`resume_ev_id`, `resume_id`, `jd_id`, …) | List of evaluation rows. |
| **DELETE** | `/resume-evaluation` | JSON: `resume_ev_ids` and/or `resume_ids` and/or `jd_ids` (see `DeleteResumeEvaluationBody`) | `{ "count", "deleted": [...] }` |

**Rule for `/evaluate`:** If **`resume_id`** is set, the server loads the candidate from **`resume_info`** and ignores inline JSON. If **`resume_id`** is omitted, a substantive **`extracted_resume_json`** plus **`resume_path`** may be used (see validator in `EvaluateRequest`).

---

## Resume–job match (`/resume-job-match`)

Backed by **`public.fn_resume_job_match`**. Rows include scalar LLM fields, **`jd_ids`** used in the request, **`preferred_jd_id`**, and **`added_to_resume_info`** (set after **`/promote`**).

| Method | Path | Input | Output `data` (typical) |
|--------|------|--------|-------------------------|
| **POST** | `/resume-job-match` | **multipart/form-data**: `file` (required). **`jobs`** (optional string): JSON array of JD UUIDs, or object `{ "<jd_uuid>": "optional display title", ... }`, or omit / empty / `[]` / `{}` to use **all** job descriptions (if none exist in DB, **422**). | `{ "match_id", "resume_path", "name", "email", "phone", "currentrole", "preferred_job_role", "preferred_jd_id", "final_verdict", "final_justification", "jd_ids": [...] }` |
| **GET** | `/resume-job-match` | Query (all optional): `match_id`, `match_ids` (repeat param; do not combine with `match_id`), `name`, `email`, `phone`, `currentrole`, `preferred_job_role`, `preferred_jd_id`, **`added_to_resume_info`** (`true`/`false`), `limit`, `offset` | `{ "count", "rows": [...] }` |
| **POST** | `/resume-job-match/promote` | JSON: `{ "match_id": "<uuid>" }` — match must exist; requires **`preferred_jd_id`** on the match row | `{ "match_id", "resume_id", "resume_path", "evaluation_id", "extracted_data", "evaluation", "added_to_resume_info": true }` — re-extracts PDF from `resume/`, inserts **`resume_info`**, runs evaluation, sets **`added_to_resume_info`** on the match row. |
| **DELETE** | `/resume-job-match` | JSON: `{ "match_ids": ["<uuid>", ...] }` | `{ "count", "deleted": [...] }` (deleted rows from the function). |

**Note:** For **`POST /resume-job-match`**, the PDF is saved under **`resume/`** before the job-match Gemini call. If Gemini fails after save, you may have a file on disk without a matching DB row.

**Debug:** The job-match prompt text may be written to **`prompt2.txt`** in the working directory (best-effort; failures are logged only).

---

## Gemini layer (`src/api/v1/endpoints/llm_gemini.py`)

- **`run_extraction(pdf_bytes)`** — PDF + parsing prompt → **`ResumeInfo`** (JSON schema).
- **`run_evaluation(resume_json, jd_row)`** — Evaluator prompt; returns **`EvaluationOutput`**.
- **`run_resume_job_match_pdf(pdf_bytes, prompt)`** — Job-match prompt; returns **`ResumeJobMatchOutput`**.

All use **`asyncio.to_thread`** for the blocking GenAI client.

---

## Optional legacy routes (`main.py`)

If `src/services/extract` and `src/services/evaluate` import successfully, extra routers mount under **`/api/resume`**. **`POST /api/resume/extract-and-evaluate`** chains extract → evaluate on a **temporary** file under `temp_uploads/` (not the main `resume/` store).

---

## Tests

- `tests/test_resume_evaluation.py` — **`EvaluateRequest`** / inline-vs-DB behavior (`python -m unittest tests.test_resume_evaluation -v`).
- `tests/test_resume_job_match.py` — `jobs` JSON parsing for job match.
