# SeaHire API

FastAPI service that stores job descriptions and candidate resumes in **PostgreSQL** (via SQL functions), runs **Google Gemini** for PDF extraction, resume–job **matching**, and related **evaluation** flows where configured, and persists structured data in the database.

## Business goal

Recruiters and hiring workflows need a **repeatable way** to:

1. **Store** open roles (**job descriptions**) and **candidates** ( **`candidates`** + **`candidate_eval`**; legacy **`resume_info`** is deprecated) in one system of record.
2. **Turn PDFs into structured data** (skills, experience, education) so they can be searched and reused.
3. **Match** a resume against one or more roles (**resume_job_match**) and record the preferred role and JD.
4. **Score a candidate against a specific job** with **consistent criteria** (knowledge areas, technical skills, experience, certifications, overall verdict).
5. **Keep an audit trail**: stored rows linked to `resume_id`, `jd_id`, and `match_id` where applicable.

The API is the backend for that pipeline: ingest → extract / match → evaluate → persist.

## Why it is built this way

### PostgreSQL functions (`fn_job_description`, `fn_candidates`, `fn_candidate_eval`, `fn_resume_job_match`, legacy `fn_resume_info`, and others per route)

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
| Candidates | `/candidates` | **`public.fn_candidates`** + **`public.fn_candidate_eval`**; requirements-aligned Gemini eval and listing. |
| Resume–job match | `/resume-job-match` | Match PDF to one or more JDs, list, delete, **`/promote`** via **`public.fn_resume_job_match`**. |
| Resume info | `/resume-info` | **Deprecated** — legacy **`resume_info`** / **`fn_resume_info`** (see end of this file). |

---

## Job descriptions (`/api/v1/job_description`)

All routes return a **`BaseResponse`**. On success, **`data`** is typically a **JSON array** of row objects returned from **`public.fn_job_description`** (may be empty, one row, or many rows depending on the call). Field names mirror the database (for example `jd_id`, `title`, nested JSON/JSONB columns as returned by Postgres). Exact columns depend on your migrated schema; request bodies are defined in **`src/schemas/job_description.py`**.

### `GET /api/v1/job_description`

**Purpose:** List job descriptions, or fetch one by id.

| Input | Format |
|--------|--------|
| Query parameter **`uuid`** (optional) | UUID string. When set, **`fn_job_description` mode 1** returns the row where **`jd_id`** equals **`uuid`**. When omitted, **`p_jd_id`** is null and the function returns **all** job description rows. |

**Output (`data`):** `array` — each element is a job description row (JSON-serialized).

---

### `POST /api/v1/job_description`

**Purpose:** Create a new job description. HTTP **201** on success.

| Input | Format |
|--------|--------|
| Body | **`application/json`** — **`JobDescriptionCreate`** |

**`JobDescriptionCreate` shape (top level):**

| Field | Type | Notes |
|--------|------|--------|
| `dossier_id` | string or omitted | Optional external dossier id. |
| `created_by` | string or omitted | Optional creator label (e.g. recruiter email). |
| `jobDetails` | object (required) | **`JobDetailsBlock`**: `title`, `department`, `level`, `location`, `employment_type`, `remote_allowed`, **`status`**, **`openings`** (see schema for required vs optional). |
| `reporting` | object | **`ReportingBlock`**: `hiring_manager`, `reporting_to`. |
| `experience` | object | **`ExperienceBlock`**: optional `text` (free-text experience line). |
| `compensation` | object | **`CompensationBlock`**: `min_salary`, `max_salary`. |
| `content` | object (required) | **`ContentBlock`**: **`description`** (string), **`responsibilities`** (array of strings; may be empty). |
| `requirements` | object | Stored as JSONB; keys are usually requirement section titles; values are structured per your contract with the evaluator prompt. Default `{}`. |

The server generates a new **`jd_id`** server-side and passes the body into **`build_fn_jobs_args_create`** → **`fn_job_description`** insert.

**Output (`data`):** `array` — inserted row(s) as returned by the function.

---

### `PUT /api/v1/job_description/{job_uuid}`

**Purpose:** Partial update; only fields present in the body are applied.

| Input | Format |
|--------|--------|
| Path **`job_uuid`** | UUID of the job to update. |
| Body | **`application/json`** — **`JobDescriptionUpdate`** — all fields optional: `dossier_id`, `updated_by`, `jobDetails` (partial), `reporting`, `experience`, `compensation`, `content`, `requirements`. |

**Output (`data`):** `array` — updated row(s). **404** if no row matched **`job_uuid`**.

---

### `DELETE /api/v1/job_description/{job_uuid}`

**Purpose:** Delete one job description by id.

| Input | Format |
|--------|--------|
| Path **`job_uuid`** | UUID to delete. |

**Output (`data`):** `array` — deleted row(s) from **`RETURNING`**. **404** if nothing was deleted.

---

## Candidates (`/api/v1/candidates`)

Primary store: **`public.candidates`** (resume metadata + path) and **`public.candidate_eval`** (one evaluation run per candidate + JD, with structured **`evaluations`** JSONB and final scores). Listing endpoints enrich rows with **`all_evaluations`**. Schema reference: **`src/schemas/candidates_eval.py`** (`CandidatesEvalOutput`, `CandidateEvalLine`).

### `POST /api/v1/candidates` (evaluate / ingest)

**Purpose:** Run the **requirements-aligned Gemini evaluation** for a given **`jd_id`**, then persist **`candidate_eval`**. Either **create a new candidate** from an uploaded resume, or **re-evaluate** an existing candidate’s stored PDF against the same or another JD.

| Input | Format |
|--------|--------|
| Content type | **`multipart/form-data`** |
| **`jd_id`** (form field, required) | String UUID of a row in **`job_description`** (must exist or **404**). |
| **`file`** (form file, optional) | Resume **PDF**, **DOC**, or **DOCX**. When present (non-empty filename), treated as **new candidate** path. |
| **`candidate_id`** (form field, optional) | String UUID of an existing **`candidates.candidate_id`**. When used **without** `file`, the server loads **`resume_path`** from DB and reads the PDF from **`resume/`**. |

**Rules:**

- Send **`file` + `jd_id`** **or** **`candidate_id` + `jd_id`** — **not both** (**422** if both).
- Omitting both file and **`candidate_id`** → **422**.

**New candidate path (`file` + `jd_id`):**

1. Normalize upload to PDF, call Gemini with JD context + PDF → **`CandidatesEvalOutput`**.
2. Save PDF under **`resume/`** using a basename derived from extracted name.
3. Insert **`candidates`** (new **`candidate_id`**).
4. Insert **`candidate_eval`** (new **`evaluation_id`**; prior row for same `(candidate_id, jd_id)` is replaced per SQL).

**Output (`data`) — upload path:**

| Field | Type | Description |
|--------|------|-------------|
| `candidate_id` | string (UUID) | New candidate id. |
| `evaluation_id` | string (UUID) | New evaluation run id. |
| `resume_path` | string | Filename under **`resume/`**. |
| `candidate_row` | object | **`candidates`** row as returned from DB. |
| `evaluation_row` | object | **`candidate_eval`** row; **`evaluations`** is nested JSON (section → array of line objects with `skill`, `expected`, `candidate`, `rating`). |

**Re-eval path (`candidate_id` + `jd_id`):**

1. Load candidate; require **`resume_path`** and existing file on disk (**422**/**404** if invalid).
2. Same Gemini + **`candidate_eval`** insert as above for that **`candidate_id`**.

**Output (`data`) — re-eval path:**

| Field | Type | Description |
|--------|------|-------------|
| `candidate_id` | string (UUID) | Same as request. |
| `evaluation_id` | string (UUID) | New evaluation run id. |
| `resume_path` | string | Basename from candidate row. |
| `evaluation_row` | object | As above (no new **`candidate_row`** in this response). |

---

### `GET /api/v1/candidates`

**Purpose:** Page and filter **`candidates`**; attach **`all_evaluations`** per id.

| Query parameter | Type | Description |
|-----------------|------|-------------|
| `candidate_name` | string | Case-insensitive substring on **`candidate_name`**. |
| `phone` | string | Case-insensitive substring on **`phone`**. |
| `email` | string | Case-insensitive substring on **`email`**. |
| `years_min` | number | Minimum **`years_of_experience`** (inclusive). |
| `years_max` | number | Maximum **`years_of_experience`** (inclusive). |
| `present_role` | string, repeatable | Exact match on **`present_role`**; repeat the query key for multiple values. |
| `limit` | integer | Page size, default **50**, **1–500**. |
| `offset` | integer | Rows to skip, default **0**. |

**Output (`data`):**

| Field | Type | Description |
|--------|------|-------------|
| `rows` | array | Each item: **`candidates`** columns plus **`all_evaluations`**: list of **`candidate_eval`** rows for that **`candidate_id`** (with **`evaluations`** JSON decoded when possible). |
| `limit` | integer | Echo of applied limit. |
| `offset` | integer | Echo of offset. |
| `count` | integer | Number of rows in **`rows`**. |

---

### `GET /api/v1/candidates/evaluations`

**Purpose:** Filter **`candidate_eval`** rows, then return **one combined row per distinct `candidate_id`** in the filtered result (same enrichment pattern as **`GET /candidates`**: candidate base row + **`all_evaluations`** for that candidate).

| Query parameter | Type | Description |
|-----------------|------|-------------|
| `evaluation_id` | string (UUID) | Exact evaluation id. |
| `candidate_id` | string (UUID) | Single candidate filter. |
| `jd_id` | string (UUID) | Single JD filter. |
| `candidate_ids` | string, repeatable | Restrict to these candidate ids (repeat query key). |
| `final_rating_min` | integer | **`final_rating` ≥** value. |
| `final_rating_max` | integer | **`final_rating` ≤** value. |
| `final_verdict` | string, repeatable | Exact **`final_verdict`** match (repeat for OR-style multiple values, per SQL). |
| `limit` | integer, optional | If omitted, no cap in app (subject to DB). If set, **1–10000**. |
| `offset` | integer | Default **0**. |

**Output (`data`):**

| Field | Type | Description |
|--------|------|-------------|
| `rows` | array | One object per distinct candidate in the evaluation result set; each includes **`all_evaluations`** (full list for that candidate, not only the filter hit). |
| `limit` | integer or null | Echo. |
| `offset` | integer | Echo. |
| `count` | integer | Length of **`rows`**. |

---

### `DELETE /api/v1/candidates`

**Purpose:** Delete one or many **`candidates`** by id. Related **`candidate_eval`** rows cascade in the database. The app **best-effort deletes** the resume file under **`resume/`** when **`resume_path`** is a safe basename.

| Input | Format |
|--------|--------|
| Body | **`application/json`** |

```json
{
  "candidate_ids": ["<uuid>", "..."]
}
```

- **`candidate_ids`**: required, **1–500** UUID strings (duplicates are deduped).
- If exactly **one** id was sent and no DB row matched → **404**.

**Output (`data`):**

| Field | Type | Description |
|--------|------|-------------|
| `requested_count` | integer | Number of ids after parse/dedupe. |
| `deleted_count` | integer | Rows returned from delete. |
| `deleted` | array | Deleted **`candidates`** rows (as returned by **`fn_candidates`** mode 3). |
| `missing_candidate_ids` | array of strings | Requested ids that did not appear in **`deleted`** (e.g. already gone). |

---

## Resume info (`/api/v1/resume-info`) — **deprecated**

These routes remain mounted for backward compatibility. **Prefer `/api/v1/candidates`** for new work: candidates carry **`resume_path`**, evaluations live in **`candidate_eval`**, and **`POST /candidates`** performs the supported PDF + JD evaluation flow.

| Method | Path | Input format | Output `data` format |
|--------|------|----------------|----------------------|
| **GET** | `/resume-info` | **Query string** — optional filters: `resume_id` (UUID), `candidate_name`, `email`, `phone`, `location`, `linkedin`, `total_experience_years`, `min_experience`, `max_experience`, `skills` (JSON array string), `evaluated`, `created_from`, `created_to`, `limit` (1–500, default 20), `offset` (≥ 0). | `{ "count": <int>, "items": [ ... ] }` — each item is a **`resume_info`** row plus **`evaluations`**: always an **empty array** in the current app (legacy field retained for clients). |
| **POST** | `/resume-info/extract` | **multipart/form-data** — **`file`**: PDF/DOC/DOCX; **`jd_id`**: string UUID (reserved for future use on this route). | `{ "resume_id", "resume_path", "extracted_data" }` — **`extracted_data`** matches **`ResumeInfo`** in **`src/schemas/resume.py`**. |
| **DELETE** | `/resume-info` | **JSON body** — **`DeleteResumeInfoBody`**: `{ "resume_ids": ["<uuid>", ...] }` (min one UUID). | `{ "count", "deleted": [...] }` — **`deleted`** is the array of rows returned from **`fn_resume_info`** mode 4. |

**Deprecated flow (extract):** upload → normalize to PDF → Gemini extraction → save under **`resume/`** → insert **`resume_info`**. Failures before insert do not leave a DB row; file save failures surface as **500** with detail.

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

- `tests/test_resume_job_match.py` — `jobs` JSON parsing for job match (when present in the repo).
