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

## Source of truth

- **`candidates.sql`** + **`candidates_eval.sql`** define the current schema and functions.
