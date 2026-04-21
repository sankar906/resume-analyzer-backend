-- public.resume_job_match definition

-- Drop table

-- DROP TABLE public.resume_job_match;

CREATE TABLE public.resume_job_match (
	match_id uuid DEFAULT gen_random_uuid() NOT NULL,
	resume_path text NOT NULL,
	"name" text NULL,
	email text NULL,
	phone text NULL,
	currentrole text NULL,
	preferred_job_role text NULL,
	final_verdict text NULL,
	final_justification text NULL,
	jd_ids _uuid NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	preferred_jd_id uuid NULL,
	added_to_resume_info bool NULL,
	CONSTRAINT resume_job_match_pkey PRIMARY KEY (match_id)
);


-- DROP FUNCTION public.fn_resume_job_match(
--   int4, text, text, text, text, text, text, uuid,
--   text, text, _uuid, uuid, int4, int4, _uuid, bool
-- );

CREATE OR REPLACE FUNCTION public.fn_resume_job_match(
	p_mode integer,
	p_resume_path text DEFAULT NULL,
	p_name text DEFAULT NULL,
	p_email text DEFAULT NULL,
	p_phone text DEFAULT NULL,
	p_currentrole text DEFAULT NULL,
	p_preferred_job_role text DEFAULT NULL,
	p_preferred_jd_id uuid DEFAULT NULL,
	p_final_verdict text DEFAULT NULL,
	p_final_justification text DEFAULT NULL,
	p_jd_ids uuid[] DEFAULT NULL,
	p_match_id uuid DEFAULT NULL,
	p_limit integer DEFAULT NULL,
	p_offset integer DEFAULT 0,
	p_match_ids uuid[] DEFAULT NULL,
	p_added_to_resume_info bool DEFAULT NULL   -- ✅ NEW PARAM
)
RETURNS TABLE(
	match_id uuid,
	resume_path text,
	name text,
	email text,
	phone text,
	currentrole text,
	preferred_job_role text,
	preferred_jd_id uuid,
	final_verdict text,
	final_justification text,
	jd_ids uuid[],
	added_to_resume_info bool,   -- ✅ NEW COLUMN
	created_at timestamp without time zone
)
LANGUAGE plpgsql
AS $function$
BEGIN

	--------------------------------------------------
	-- MODE 1: INSERT
	--------------------------------------------------
	IF p_mode = 1 THEN
		RETURN QUERY
		INSERT INTO public.resume_job_match AS ins (
			resume_path,
			name,
			email,
			phone,
			currentrole,
			preferred_job_role,
			preferred_jd_id,
			final_verdict,
			final_justification,
			jd_ids,
			added_to_resume_info           -- ✅ NEW
		)
		VALUES (
			p_resume_path,
			p_name,
			p_email,
			p_phone,
			p_currentrole,
			p_preferred_job_role,
			p_preferred_jd_id,
			p_final_verdict,
			p_final_justification,
			p_jd_ids,
			p_added_to_resume_info         -- ✅ NEW
		)
		RETURNING
			ins.match_id,
			ins.resume_path,
			ins.name,
			ins.email,
			ins.phone,
			ins.currentrole,
			ins.preferred_job_role,
			ins.preferred_jd_id,
			ins.final_verdict,
			ins.final_justification,
			ins.jd_ids,
			ins.added_to_resume_info,     -- ✅ NEW
			ins.created_at;

	--------------------------------------------------
	-- MODE 2: GET
	--------------------------------------------------
	ELSIF p_mode = 2 THEN

		IF p_match_id IS NOT NULL
			AND p_match_ids IS NOT NULL
			AND array_length(p_match_ids, 1) IS NOT NULL
		THEN
			RAISE EXCEPTION 'Use either p_match_id or p_match_ids for filter, not both';
		END IF;

		RETURN QUERY
		SELECT
			m.match_id,
			m.resume_path,
			m.name,
			m.email,
			m.phone,
			m.currentrole,
			m.preferred_job_role,
			m.preferred_jd_id,
			m.final_verdict,
			m.final_justification,
			m.jd_ids,
			m.added_to_resume_info,       -- ✅ NEW
			m.created_at
		FROM public.resume_job_match m
		WHERE
			(
				(
					p_match_ids IS NOT NULL
					AND array_length(p_match_ids, 1) IS NOT NULL
					AND m.match_id = ANY(p_match_ids)
				)
				OR
				(
					(p_match_ids IS NULL OR array_length(p_match_ids, 1) IS NULL)
					AND (p_match_id IS NULL OR m.match_id = p_match_id)
				)
			)
			AND (p_name IS NULL OR m.name ILIKE '%' || p_name || '%')
			AND (p_email IS NULL OR m.email ILIKE '%' || p_email || '%')
			AND (p_phone IS NULL OR m.phone ILIKE '%' || p_phone || '%')
			AND (p_currentrole IS NULL OR m.currentrole ILIKE '%' || p_currentrole || '%')
			AND (
				p_preferred_job_role IS NULL
				OR m.preferred_job_role ILIKE '%' || p_preferred_job_role || '%'
			)
			AND (p_preferred_jd_id IS NULL OR m.preferred_jd_id = p_preferred_jd_id)
			AND (
				p_added_to_resume_info IS NULL
				OR m.added_to_resume_info = p_added_to_resume_info   -- ✅ NEW FILTER
			)
		ORDER BY m.created_at DESC
		LIMIT p_limit
		OFFSET COALESCE(p_offset, 0);

	--------------------------------------------------
	-- MODE 4: DELETE
	--------------------------------------------------
	ELSIF p_mode = 4 THEN
		IF p_match_ids IS NULL OR array_length(p_match_ids, 1) IS NULL THEN
			RAISE EXCEPTION 'p_match_ids is required and must be non-empty for delete (mode 4)';
		END IF;

		RETURN QUERY
		DELETE FROM public.resume_job_match m
		WHERE m.match_id = ANY(p_match_ids)
		RETURNING
			m.match_id,
			m.resume_path,
			m.name,
			m.email,
			m.phone,
			m.currentrole,
			m.preferred_job_role,
			m.preferred_jd_id,
			m.final_verdict,
			m.final_justification,
			m.jd_ids,
			m.added_to_resume_info,
			m.created_at;

	--------------------------------------------------
	-- MODE 5: set added_to_resume_info (e.g. after POST /resume-job-match/promote)
	--------------------------------------------------
	ELSIF p_mode = 5 THEN
		IF p_match_id IS NULL THEN
			RAISE EXCEPTION 'p_match_id is required for mode 5';
		END IF;

		RETURN QUERY
		UPDATE public.resume_job_match m
		SET added_to_resume_info = COALESCE(p_added_to_resume_info, true)
		WHERE m.match_id = p_match_id
		RETURNING
			m.match_id,
			m.resume_path,
			m.name,
			m.email,
			m.phone,
			m.currentrole,
			m.preferred_job_role,
			m.preferred_jd_id,
			m.final_verdict,
			m.final_justification,
			m.jd_ids,
			m.added_to_resume_info,
			m.created_at;

	ELSE
		RAISE EXCEPTION 'Invalid mode. Use 1=INSERT, 2=GET/filter, 4=DELETE, 5=SET added_to_resume_info';
	END IF;

END;
$function$;