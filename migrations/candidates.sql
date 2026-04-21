-- public.candidates + public.fn_candidates (modes 1–3).
-- Mode 1: INSERT. Mode 2: SELECT (single/multiple ids via p_candidate_ids, or list-all with optional filters; no candidate_eval).
-- Mode 3: DELETE WHERE candidate_id = ANY(p_candidate_ids).

DROP FUNCTION IF EXISTS public.fn_candidates CASCADE;
DROP TABLE IF EXISTS public.candidates CASCADE;

CREATE TABLE public.candidates (
    candidate_id uuid NOT NULL,
    candidate_name text NULL,
    phone text NULL,
    email text NULL,
    years_of_experience numeric NULL,
    present_role text NULL,
    resume_path text NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT candidates_pkey PRIMARY KEY (candidate_id)
);

CREATE OR REPLACE FUNCTION public.fn_candidates(
    p_mode integer,
    p_candidate_id uuid DEFAULT NULL::uuid,
    p_candidate_name text DEFAULT NULL::text,
    p_phone text DEFAULT NULL::text,
    p_email text DEFAULT NULL::text,
    p_years_of_experience numeric DEFAULT NULL::numeric,
    p_present_role text DEFAULT NULL::text,
    p_resume_path text DEFAULT NULL::text,
    p_years_min numeric DEFAULT NULL::numeric,
    p_years_max numeric DEFAULT NULL::numeric,
    p_present_roles text[] DEFAULT NULL::text[],
    p_candidate_ids uuid[] DEFAULT NULL::uuid[],
    p_limit integer DEFAULT NULL::integer,
    p_offset integer DEFAULT NULL::integer
)
RETURNS TABLE(
    candidate_id uuid,
    candidate_name text,
    phone text,
    email text,
    years_of_experience numeric,
    present_role text,
    resume_path text,
    created_at timestamp without time zone
)
LANGUAGE plpgsql
AS $function$
DECLARE
    v_lim int;
    v_off int;
BEGIN
    IF p_mode = 1 THEN
        RETURN QUERY
        INSERT INTO public.candidates (
            candidate_id,
            candidate_name,
            phone,
            email,
            years_of_experience,
            present_role,
            resume_path
        )
        VALUES (
            p_candidate_id,
            p_candidate_name,
            p_phone,
            p_email,
            p_years_of_experience,
            p_present_role,
            p_resume_path
        )
        RETURNING *;
    ELSIF p_mode = 2 THEN
        v_lim := COALESCE(NULLIF(p_limit, 0), 100);
        IF v_lim > 500 THEN
            v_lim := 500;
        END IF;
        IF v_lim < 1 THEN
            v_lim := 1;
        END IF;
        v_off := GREATEST(COALESCE(p_offset, 0), 0);

        RETURN QUERY
        SELECT
            c.candidate_id,
            c.candidate_name,
            c.phone,
            c.email,
            c.years_of_experience,
            c.present_role,
            c.resume_path,
            c.created_at
        FROM public.candidates c
        WHERE
            (
                p_candidate_ids IS NULL
                OR cardinality(p_candidate_ids) = 0
                OR c.candidate_id = ANY (p_candidate_ids)
            )
            AND (
                p_candidate_name IS NULL OR TRIM(p_candidate_name) = ''
                OR c.candidate_name ILIKE '%' || TRIM(p_candidate_name) || '%'
            )
            AND (
                p_phone IS NULL OR TRIM(p_phone) = ''
                OR c.phone ILIKE '%' || TRIM(p_phone) || '%'
            )
            AND (
                p_email IS NULL OR TRIM(p_email) = ''
                OR c.email ILIKE '%' || TRIM(p_email) || '%'
            )
            AND (
                p_years_min IS NULL OR c.years_of_experience IS NULL
                OR c.years_of_experience >= p_years_min
            )
            AND (
                p_years_max IS NULL OR c.years_of_experience IS NULL
                OR c.years_of_experience <= p_years_max
            )
            AND (
                p_present_roles IS NULL
                OR cardinality(p_present_roles) = 0
                OR (c.present_role IS NOT NULL AND c.present_role = ANY (p_present_roles))
            )
        ORDER BY c.created_at DESC
        LIMIT v_lim
        OFFSET v_off;
    ELSIF p_mode = 3 THEN
        IF p_candidate_ids IS NULL OR cardinality(p_candidate_ids) = 0 THEN
            RAISE EXCEPTION 'fn_candidates mode 3 requires non-empty p_candidate_ids';
        END IF;
        RETURN QUERY
        DELETE FROM public.candidates c
        WHERE c.candidate_id = ANY (p_candidate_ids)
        RETURNING
            c.candidate_id,
            c.candidate_name,
            c.phone,
            c.email,
            c.years_of_experience,
            c.present_role,
            c.resume_path,
            c.created_at;
    ELSE
        RAISE EXCEPTION 'Invalid mode for fn_candidates. Use 1=INSERT, 2=SELECT, 3=DELETE';
    END IF;
END;
$function$;
