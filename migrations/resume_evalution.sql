-- public.resume_evaluation definition

-- Drop table

-- DROP TABLE public.resume_evaluation;

CREATE TABLE public.resume_evaluation (
	resume_ev_id uuid DEFAULT gen_random_uuid() NOT NULL,
	resume_id uuid NULL,
	evaluation jsonb NULL,
	final_rating int4 NULL,
	final_verdict text NULL,
	final_justification text NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	resume_path text NULL,
	jd_title text NULL,
	jd_id uuid NULL,
	CONSTRAINT resume_evaluation_resume_ev_id_pkey PRIMARY KEY (resume_ev_id)
);


-- DROP FUNCTION public.fn_resume_evaluation(int4, uuid, uuid, int4, int4, jsonb, int4, text, text, text, text, uuid, _uuid, _uuid, _uuid);

CREATE OR REPLACE FUNCTION public.fn_resume_evaluation(p_mode integer, p_resume_ev_id uuid DEFAULT NULL::uuid, p_resume_id uuid DEFAULT NULL::uuid, p_limit integer DEFAULT NULL::integer, p_offset integer DEFAULT 0, p_evaluation jsonb DEFAULT NULL::jsonb, p_final_rating integer DEFAULT NULL::integer, p_final_verdict text DEFAULT NULL::text, p_final_justification text DEFAULT NULL::text, p_resume_path text DEFAULT NULL::text, p_jd_title text DEFAULT NULL::text, p_jd_id uuid DEFAULT NULL::uuid, p_resume_ev_ids uuid[] DEFAULT NULL::uuid[], p_resume_ids uuid[] DEFAULT NULL::uuid[], p_jd_ids uuid[] DEFAULT NULL::uuid[])
 RETURNS TABLE(resume_ev_id uuid, resume_id uuid, evaluation jsonb, final_rating integer, final_verdict text, final_justification text, created_at timestamp without time zone, updated_at timestamp without time zone, resume_path text, jd_title text, jd_id uuid)
 LANGUAGE plpgsql
AS $function$
BEGIN

    --------------------------------------------------
    -- MODE 1: INSERT
    --------------------------------------------------
    IF p_mode = 1 THEN
        RETURN QUERY
        INSERT INTO public.resume_evaluation (
            resume_ev_id,
            resume_id,
            evaluation,
            final_rating,
            final_verdict,
            final_justification,
            resume_path,
            jd_title,
            jd_id
        )
        VALUES (
            COALESCE(p_resume_ev_id, gen_random_uuid()),
            p_resume_id,
            p_evaluation,
            p_final_rating,
            p_final_verdict,
            p_final_justification,
            p_resume_path,
            p_jd_title,
            p_jd_id
        )
        RETURNING *;

    --------------------------------------------------
    -- MODE 2: GET (UPDATED FOR BULK FILTERS)
    --------------------------------------------------
    ELSIF p_mode = 2 THEN

        -- Optional strict validation (avoid ambiguity)
        IF p_resume_ev_id IS NOT NULL AND p_resume_ev_ids IS NOT NULL THEN
            RAISE EXCEPTION 'Use either p_resume_ev_id or p_resume_ev_ids';
        END IF;

        IF p_resume_id IS NOT NULL AND p_resume_ids IS NOT NULL THEN
            RAISE EXCEPTION 'Use either p_resume_id or p_resume_ids';
        END IF;

        IF p_jd_id IS NOT NULL AND p_jd_ids IS NOT NULL THEN
            RAISE EXCEPTION 'Use either p_jd_id or p_jd_ids';
        END IF;

        RETURN QUERY
        SELECT *
        FROM public.resume_evaluation re
        WHERE
            -- resume_ev_id filter
            (
                (p_resume_ev_ids IS NOT NULL AND re.resume_ev_id = ANY(p_resume_ev_ids))
                OR
                (p_resume_ev_ids IS NULL AND (p_resume_ev_id IS NULL OR re.resume_ev_id = p_resume_ev_id))
            )

            AND
            -- resume_id filter
            (
                (p_resume_ids IS NOT NULL AND re.resume_id = ANY(p_resume_ids))
                OR
                (p_resume_ids IS NULL AND (p_resume_id IS NULL OR re.resume_id = p_resume_id))
            )

            AND
            -- jd_id filter
            (
                (p_jd_ids IS NOT NULL AND re.jd_id = ANY(p_jd_ids))
                OR
                (p_jd_ids IS NULL AND (p_jd_id IS NULL OR re.jd_id = p_jd_id))
            )

            AND (p_final_rating IS NULL OR re.final_rating = p_final_rating)
            AND (p_final_verdict IS NULL OR re.final_verdict ILIKE '%' || p_final_verdict || '%')
            AND (p_jd_title IS NULL OR re.jd_title ILIKE '%' || p_jd_title || '%')

        ORDER BY re.created_at DESC
        LIMIT p_limit
        OFFSET COALESCE(p_offset, 0);

    --------------------------------------------------
    -- MODE 3: UPDATE
    --------------------------------------------------
    ELSIF p_mode = 3 THEN
        RETURN QUERY
        UPDATE public.resume_evaluation re
        SET 
            evaluation = COALESCE(p_evaluation, re.evaluation),
            final_rating = COALESCE(p_final_rating, re.final_rating),
            final_verdict = COALESCE(p_final_verdict, re.final_verdict),
            final_justification = COALESCE(p_final_justification, re.final_justification),
            resume_path = COALESCE(p_resume_path, re.resume_path),
            jd_title = COALESCE(p_jd_title, re.jd_title),
            jd_id = COALESCE(p_jd_id, re.jd_id),
            updated_at = CURRENT_TIMESTAMP
        WHERE re.resume_ev_id = p_resume_ev_id
        RETURNING *;

    --------------------------------------------------
    -- MODE 4: DELETE (UNCHANGED)
    --------------------------------------------------
    ELSIF p_mode = 4 THEN

        IF p_resume_ev_id IS NULL 
           AND p_resume_id IS NULL 
           AND p_jd_id IS NULL
           AND (p_resume_ev_ids IS NULL OR array_length(p_resume_ev_ids,1) IS NULL)
           AND (p_resume_ids IS NULL OR array_length(p_resume_ids,1) IS NULL)
           AND (p_jd_ids IS NULL OR array_length(p_jd_ids,1) IS NULL)
        THEN
            RAISE EXCEPTION 'At least one identifier is required for delete';
        END IF;

        RETURN QUERY
        DELETE FROM public.resume_evaluation re
        WHERE
            (p_resume_ev_id IS NOT NULL AND re.resume_ev_id = p_resume_ev_id)
            OR (p_resume_id IS NOT NULL AND re.resume_id = p_resume_id)
            OR (p_jd_id IS NOT NULL AND re.jd_id = p_jd_id)
            OR (p_resume_ev_ids IS NOT NULL AND re.resume_ev_id = ANY(p_resume_ev_ids))
            OR (p_resume_ids IS NOT NULL AND re.resume_id = ANY(p_resume_ids))
            OR (p_jd_ids IS NOT NULL AND re.jd_id = ANY(p_jd_ids))
        RETURNING *;

    ELSE
        RAISE EXCEPTION 'Invalid mode. Use 1=INSERT, 2=GET, 3=UPDATE, 4=DELETE';
    END IF;

END;
$function$
;
