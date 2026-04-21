-- public.resume_info definition

-- Drop table

-- DROP TABLE public.resume_info;

CREATE TABLE public.resume_info (
	resume_id uuid DEFAULT gen_random_uuid() NOT NULL,
	candidate_name text NULL,
	email text NULL,
	phone text NULL,
	"location" text NULL,
	linkedin text NULL,
	summary text NULL,
	total_experience_years numeric NULL,
	currentrole text NULL,
	skills jsonb NULL,
	experience jsonb NULL,
	education jsonb NULL,
	projects jsonb NULL,
	certifications jsonb NULL,
	languages jsonb NULL,
	evaluated bool DEFAULT false NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	resume_path text NULL,
	CONSTRAINT resume_info_resume_id_pkey PRIMARY KEY (resume_id)
);


-- DROP FUNCTION public.fn_resume_info(int4, uuid, int4, int4, text, text, text, text, text, text, numeric, text, jsonb, jsonb, jsonb, jsonb, jsonb, jsonb, bool, text, numeric, numeric, _uuid, timestamp, timestamp);

CREATE OR REPLACE FUNCTION public.fn_resume_info(p_mode integer, p_resume_id uuid DEFAULT NULL::uuid, p_limit integer DEFAULT NULL::integer, p_offset integer DEFAULT 0, p_candidate_name text DEFAULT NULL::text, p_email text DEFAULT NULL::text, p_phone text DEFAULT NULL::text, p_location text DEFAULT NULL::text, p_linkedin text DEFAULT NULL::text, p_summary text DEFAULT NULL::text, p_total_experience_years numeric DEFAULT NULL::numeric, p_currentrole text DEFAULT NULL::text, p_skills jsonb DEFAULT NULL::jsonb, p_experience jsonb DEFAULT NULL::jsonb, p_education jsonb DEFAULT NULL::jsonb, p_projects jsonb DEFAULT NULL::jsonb, p_certifications jsonb DEFAULT NULL::jsonb, p_languages jsonb DEFAULT NULL::jsonb, p_evaluated boolean DEFAULT NULL::boolean, p_resume_path text DEFAULT NULL::text, p_min_experience numeric DEFAULT NULL::numeric, p_max_experience numeric DEFAULT NULL::numeric, p_resume_ids uuid[] DEFAULT NULL::uuid[], p_created_from timestamp without time zone DEFAULT NULL::timestamp without time zone, p_created_to timestamp without time zone DEFAULT NULL::timestamp without time zone)
 RETURNS TABLE(resume_id uuid, candidate_name text, email text, phone text, location text, linkedin text, summary text, total_experience_years numeric, currentrole text, skills jsonb, experience jsonb, education jsonb, projects jsonb, certifications jsonb, languages jsonb, evaluated boolean, created_at timestamp without time zone, updated_at timestamp without time zone, resume_path text)
 LANGUAGE plpgsql
AS $function$
BEGIN

    --------------------------------------------------
    -- MODE 1: INSERT
    --------------------------------------------------
    IF p_mode = 1 THEN
        RETURN QUERY
        INSERT INTO public.resume_info (
            resume_id,
            candidate_name,
            email,
            phone,
            location,
            linkedin,
            summary,
            total_experience_years,
            currentrole,
            skills,
            experience,
            education,
            projects,
            certifications,
            languages,
            evaluated,
            resume_path
        )
        VALUES (
            COALESCE(p_resume_id, gen_random_uuid()),
            p_candidate_name,
            p_email,
            p_phone,
            p_location,
            p_linkedin,
            p_summary,
            p_total_experience_years,
            p_currentrole,
            p_skills,
            p_experience,
            p_education,
            p_projects,
            p_certifications,
            p_languages,
            COALESCE(p_evaluated, false),
            p_resume_path
        )
        RETURNING *;

    --------------------------------------------------
    -- MODE 2: GET (WITH MULTI-ID SUPPORT)
    --------------------------------------------------
    ELSIF p_mode = 2 THEN

        -- Prevent ambiguous usage
        IF p_resume_id IS NOT NULL AND p_resume_ids IS NOT NULL THEN
            RAISE EXCEPTION 'Provide either p_resume_id or p_resume_ids, not both';
        END IF;

        RETURN QUERY
        SELECT *
        FROM public.resume_info ri
        WHERE
            -- Single or multiple ID filter
            (
                (p_resume_ids IS NOT NULL AND ri.resume_id = ANY(p_resume_ids))
                OR
                (p_resume_ids IS NULL AND (p_resume_id IS NULL OR ri.resume_id = p_resume_id))
            )

            AND (p_candidate_name IS NULL OR ri.candidate_name ILIKE '%' || p_candidate_name || '%')
            AND (p_email IS NULL OR ri.email = p_email)
            AND (p_phone IS NULL OR ri.phone ILIKE '%' || p_phone || '%')
            AND (p_location IS NULL OR ri.location ILIKE '%' || p_location || '%')
            AND (p_linkedin IS NULL OR ri.linkedin = p_linkedin)
            AND (p_total_experience_years IS NULL OR ri.total_experience_years = p_total_experience_years)
            AND (p_min_experience IS NULL OR ri.total_experience_years >= p_min_experience)
            AND (p_max_experience IS NULL OR ri.total_experience_years <= p_max_experience)
            AND (p_skills IS NULL OR ri.skills @> p_skills)
            AND (p_evaluated IS NULL OR ri.evaluated = p_evaluated)

            -- created_at filter only
            AND (p_created_from IS NULL OR ri.created_at >= p_created_from)
            AND (p_created_to IS NULL OR ri.created_at <= p_created_to)

        ORDER BY ri.created_at DESC
        LIMIT p_limit
        OFFSET COALESCE(p_offset, 0);

    --------------------------------------------------
    -- MODE 3: UPDATE
    --------------------------------------------------
    ELSIF p_mode = 3 THEN
        RETURN QUERY
        UPDATE public.resume_info ri
        SET 
            evaluated = COALESCE(p_evaluated, ri.evaluated),
            resume_path = COALESCE(p_resume_path, ri.resume_path),
            updated_at = CURRENT_TIMESTAMP
        WHERE ri.resume_id = p_resume_id
        RETURNING *;

    --------------------------------------------------
    -- MODE 4: DELETE (BULK)
    --------------------------------------------------
    ELSIF p_mode = 4 THEN

        IF p_resume_ids IS NULL OR array_length(p_resume_ids, 1) IS NULL THEN
            RAISE EXCEPTION 'p_resume_ids cannot be null or empty for delete';
        END IF;

        RETURN QUERY
        DELETE FROM public.resume_info ri
        WHERE ri.resume_id = ANY(p_resume_ids)
        RETURNING *;

    --------------------------------------------------
    -- INVALID MODE
    --------------------------------------------------
    ELSE
        RAISE EXCEPTION 'Invalid mode. Use 1=INSERT, 2=GET, 3=UPDATE, 4=DELETE';
    END IF;

END;
$function$
;
