-- public.candidate_eval + public.fn_candidate_eval.
-- Prerequisite: public.candidates must exist (migrations/candidates.sql — TABLE section).

DROP FUNCTION IF EXISTS public.fn_candidate_eval CASCADE;
DROP TABLE IF EXISTS public.candidate_eval CASCADE;

CREATE TABLE public.candidate_eval (
    evaluation_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    jd_id uuid NOT NULL,
    jd_title text NULL,
    evaluations jsonb NULL,
    final_rating integer NULL,
    final_verdict text NULL,
    final_justification text NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT candidate_eval_pkey PRIMARY KEY (evaluation_id),
    CONSTRAINT candidate_eval_candidate_fk FOREIGN KEY (candidate_id)
        REFERENCES public.candidates (candidate_id) ON DELETE CASCADE
);

CREATE INDEX candidate_eval_candidate_jd_idx
    ON public.candidate_eval USING btree (candidate_id, jd_id);

CREATE OR REPLACE FUNCTION public.fn_candidate_eval(
    p_mode integer,
    p_evaluation_id uuid DEFAULT NULL::uuid,
    p_candidate_id uuid DEFAULT NULL::uuid,
    p_jd_id uuid DEFAULT NULL::uuid,
    p_jd_title text DEFAULT NULL::text,
    p_evaluations jsonb DEFAULT NULL::jsonb,
    p_final_rating integer DEFAULT NULL::integer,
    p_final_verdict text DEFAULT NULL::text,
    p_final_justification text DEFAULT NULL::text,
    p_candidate_ids uuid[] DEFAULT NULL::uuid[],
    p_final_rating_min integer DEFAULT NULL::integer,
    p_final_rating_max integer DEFAULT NULL::integer,
    p_final_verdicts text[] DEFAULT NULL::text[],
    p_limit integer DEFAULT NULL::integer,
    p_offset integer DEFAULT NULL::integer
)
RETURNS TABLE(
    evaluation_id uuid,
    candidate_id uuid,
    jd_id uuid,
    jd_title text,
    evaluations jsonb,
    final_rating integer,
    final_verdict text,
    final_justification text,
    created_at timestamp without time zone
)
LANGUAGE plpgsql
AS $function$
DECLARE
    v_lim int;
    v_off int;
    v_has_filter boolean;
BEGIN
    IF p_mode = 1 THEN
        -- Replace prior evaluation for the same (candidate_id, jd_id); leave other pairs unchanged.
        DELETE FROM public.candidate_eval ce
        WHERE ce.candidate_id = p_candidate_id
          AND ce.jd_id IS NOT DISTINCT FROM p_jd_id;

        RETURN QUERY
        INSERT INTO public.candidate_eval AS ins (
            evaluation_id,
            candidate_id,
            jd_id,
            jd_title,
            evaluations,
            final_rating,
            final_verdict,
            final_justification
        )
        VALUES (
            p_evaluation_id,
            p_candidate_id,
            p_jd_id,
            p_jd_title,
            p_evaluations,
            p_final_rating,
            p_final_verdict,
            p_final_justification
        )
        RETURNING
            ins.evaluation_id,
            ins.candidate_id,
            ins.jd_id,
            ins.jd_title,
            ins.evaluations,
            ins.final_rating,
            ins.final_verdict,
            ins.final_justification,
            ins.created_at;
    ELSIF p_mode = 2 THEN
        v_lim := COALESCE(NULLIF(p_limit, 0), 100);
        IF v_lim > 10000 THEN
            v_lim := 10000;
        END IF;
        IF v_lim < 1 THEN
            v_lim := 1;
        END IF;
        v_off := GREATEST(COALESCE(p_offset, 0), 0);

        v_has_filter := (
            p_evaluation_id IS NOT NULL
            OR p_candidate_id IS NOT NULL
            OR p_jd_id IS NOT NULL
            OR (p_candidate_ids IS NOT NULL AND cardinality(p_candidate_ids) > 0)
            OR p_final_rating_min IS NOT NULL
            OR p_final_rating_max IS NOT NULL
            OR (p_final_verdicts IS NOT NULL AND cardinality(p_final_verdicts) > 0)
        );

        RETURN QUERY
        SELECT
            ce.evaluation_id,
            ce.candidate_id,
            ce.jd_id,
            ce.jd_title,
            ce.evaluations,
            ce.final_rating,
            ce.final_verdict,
            ce.final_justification,
            ce.created_at
        FROM public.candidate_eval ce
        WHERE
            (
                NOT v_has_filter
                OR (
                    (p_evaluation_id IS NULL OR ce.evaluation_id = p_evaluation_id)
                    AND (p_candidate_id IS NULL OR ce.candidate_id = p_candidate_id)
                    AND (p_jd_id IS NULL OR ce.jd_id = p_jd_id)
                    AND (
                        p_candidate_ids IS NULL
                        OR cardinality(p_candidate_ids) = 0
                        OR ce.candidate_id = ANY (p_candidate_ids)
                    )
                    AND (
                        p_final_rating_min IS NULL
                        OR (ce.final_rating IS NOT NULL AND ce.final_rating >= p_final_rating_min)
                    )
                    AND (
                        p_final_rating_max IS NULL
                        OR (ce.final_rating IS NOT NULL AND ce.final_rating <= p_final_rating_max)
                    )
                    AND (
                        p_final_verdicts IS NULL
                        OR cardinality(p_final_verdicts) = 0
                        OR (
                            ce.final_verdict IS NOT NULL
                            AND ce.final_verdict = ANY (p_final_verdicts)
                        )
                    )
                )
            )
        ORDER BY ce.created_at DESC
        LIMIT v_lim
        OFFSET v_off;
    ELSIF p_mode = 3 THEN
        IF p_candidate_ids IS NULL OR cardinality(p_candidate_ids) = 0 THEN
            RAISE EXCEPTION 'fn_candidate_eval mode 3 requires non-empty p_candidate_ids';
        END IF;
        RETURN QUERY
        DELETE FROM public.candidate_eval ce
        WHERE ce.candidate_id = ANY (p_candidate_ids)
        RETURNING
            ce.evaluation_id,
            ce.candidate_id,
            ce.jd_id,
            ce.jd_title,
            ce.evaluations,
            ce.final_rating,
            ce.final_verdict,
            ce.final_justification,
            ce.created_at;
    ELSE
        RAISE EXCEPTION 'Invalid mode for fn_candidate_eval. Use 1=INSERT, 2=SELECT, 3=DELETE';
    END IF;
END;
$function$;
