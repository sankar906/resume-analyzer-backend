# Database migrations

## New database

Run in order:

1. **`candidates.sql`** — `public.candidates` and `public.fn_candidates` (modes: **1** INSERT, **2** SELECT with optional `p_candidate_ids` and candidate-only filters, **3** bulk DELETE by `p_candidate_ids`). Does not reference `candidate_eval`.
2. **`candidates_eval.sql`** — `public.candidate_eval` (includes **`jd_title`**, snapshot of job title at eval time), index, and `public.fn_candidate_eval` (modes: **1** INSERT with `p_jd_title` — deletes any existing row with the same `(candidate_id, jd_id)` first, **2** SELECT, **3** DELETE by `p_candidate_ids`).

`DROP TABLE public.candidates CASCADE` removes dependent `candidate_eval` if it exists; use caution on databases with data.

## Existing database (add `jd_title` without dropping data)

Run **`upgrade_candidate_eval_jd_title.sql`** — `ALTER TABLE ... ADD COLUMN jd_title`, then replaces `fn_candidate_eval` with the new signature. Do **not** re-run the full `candidates_eval.sql` if you need to keep rows (it drops the table).

## Existing database (replace eval on same candidate + JD)

If `candidate_eval` already exists, run **`upgrade_candidate_eval_replace_same_jd.sql`** — updates `fn_candidate_eval` so mode **1** deletes any existing row with the same `(candidate_id, jd_id)` before inserting the new evaluation. Safe to run on populated databases (no table drop).

## Existing database (`fn_candidate_eval` mode 2: optional row cap)

Run **`upgrade_candidate_eval_p_limit_null.sql`** so mode **2** treats **`p_limit` NULL** as “return all matching rows” (no 100-row default). API `GET …/candidates/evaluations` omits `limit` by default.

## Job descriptions

- **`job_description.sql`** — `public.job_description` with a single **`experience`** text column (no `min_experience` / `max_experience`) and **`public.fn_job_description`** (modes 1–4; `p_experience` replaces the two int params).

## Existing database (job experience as text)

Run **`upgrade_job_description_experience_text.sql`** on DBs that still have `min_experience` / `max_experience`. It adds **`experience`**, copies a best-effort string from the old ints, drops the old columns, and replaces **`fn_job_description`**.

## Source of truth

- **`candidates.sql`** + **`candidates_eval.sql`** define the current candidate schema and functions.
- **`job_description.sql`** defines job description table + function.
