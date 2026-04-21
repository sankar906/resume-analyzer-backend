-- public.job_description definition

-- Drop table

-- DROP TABLE public.job_description;

CREATE TABLE public.job_description (
	id serial4 NOT NULL,
	jd_id uuid DEFAULT gen_random_uuid() NOT NULL,
	title varchar(200) NOT NULL,
	department varchar(100) NULL,
	"location" varchar(200) NULL,
	description text NOT NULL,
	requirements jsonb NULL,
	responsibilities text NULL,
	status text NULL,
	min_experience int4 NULL,
	max_experience int4 NULL,
	min_salary int4 NULL,
	max_salary int4 NULL,
	employment_type varchar(50) NULL,
	remote_allowed bool NULL,
	hiring_manager varchar(200) NULL,
	openings int4 NOT NULL,
	dossier_id varchar(100) NULL,
	"level" varchar(100) NULL,
	reporting_to varchar(200) NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT job_description_jd_id_key UNIQUE (jd_id),
	CONSTRAINT job_description_pkey PRIMARY KEY (id)
);


-- DROP FUNCTION public.fn_job_description(int4, uuid, varchar, varchar, varchar, text, jsonb, text, text, int4, int4, int4, int4, varchar, bool, varchar, int4, varchar, varchar, varchar);

CREATE OR REPLACE FUNCTION public.fn_job_description(p_mode integer, p_jd_id uuid DEFAULT NULL::uuid, p_title character varying DEFAULT NULL::character varying, p_department character varying DEFAULT NULL::character varying, p_location character varying DEFAULT NULL::character varying, p_description text DEFAULT NULL::text, p_requirements jsonb DEFAULT NULL::jsonb, p_responsibilities text DEFAULT NULL::text, p_status text DEFAULT NULL::text, p_min_experience integer DEFAULT NULL::integer, p_max_experience integer DEFAULT NULL::integer, p_min_salary integer DEFAULT NULL::integer, p_max_salary integer DEFAULT NULL::integer, p_employment_type character varying DEFAULT NULL::character varying, p_remote_allowed boolean DEFAULT NULL::boolean, p_hiring_manager character varying DEFAULT NULL::character varying, p_openings integer DEFAULT NULL::integer, p_dossier_id character varying DEFAULT NULL::character varying, p_level character varying DEFAULT NULL::character varying, p_reporting_to character varying DEFAULT NULL::character varying)
 RETURNS TABLE(id integer, jd_id uuid, title character varying, department character varying, location character varying, description text, requirements jsonb, responsibilities text, status text, min_experience integer, max_experience integer, min_salary integer, max_salary integer, employment_type character varying, remote_allowed boolean, hiring_manager character varying, openings integer, dossier_id character varying, level character varying, reporting_to character varying, created_at timestamp with time zone, updated_at timestamp with time zone)
 LANGUAGE plpgsql
AS $function$
BEGIN

    ----------------------------------------------------------------
    -- MODE 1 = GET DATA
    ----------------------------------------------------------------
    IF p_mode = 1 THEN
        RETURN QUERY
        SELECT *
        FROM public.job_description jd
        WHERE p_jd_id IS NULL OR jd.jd_id = p_jd_id;

    ----------------------------------------------------------------
    -- MODE 2 = INSERT DATA
    ----------------------------------------------------------------
    ELSIF p_mode = 2 THEN
        RETURN QUERY
        INSERT INTO public.job_description (
            jd_id,
            title,
            department,
            location,
            description,
            requirements,
            responsibilities,
            status,
            min_experience,
            max_experience,
            min_salary,
            max_salary,
            employment_type,
            remote_allowed,
            hiring_manager,
            openings,
            dossier_id,
            level,
            reporting_to
        )
        VALUES (
            COALESCE(p_jd_id, gen_random_uuid()),
            p_title,
            p_department,
            p_location,
            p_description,
            p_requirements,
            p_responsibilities,
            p_status,
            p_min_experience,
            p_max_experience,
            p_min_salary,
            p_max_salary,
            p_employment_type,
            p_remote_allowed,
            p_hiring_manager,
            p_openings,
            p_dossier_id,
            p_level,
            p_reporting_to
        )
        RETURNING *;

    ----------------------------------------------------------------
    -- MODE 3 = UPDATE DATA BY JD_ID
    ----------------------------------------------------------------
    ELSIF p_mode = 3 THEN
        RETURN QUERY
        UPDATE public.job_description jd
        SET
            title = COALESCE(p_title, jd.title),
            department = COALESCE(p_department, jd.department),
            location = COALESCE(p_location, jd.location),
            description = COALESCE(p_description, jd.description),
            requirements = COALESCE(p_requirements, jd.requirements),
            responsibilities = COALESCE(p_responsibilities, jd.responsibilities),
            status = COALESCE(p_status, jd.status),
            min_experience = COALESCE(p_min_experience, jd.min_experience),
            max_experience = COALESCE(p_max_experience, jd.max_experience),
            min_salary = COALESCE(p_min_salary, jd.min_salary),
            max_salary = COALESCE(p_max_salary, jd.max_salary),
            employment_type = COALESCE(p_employment_type, jd.employment_type),
            remote_allowed = COALESCE(p_remote_allowed, jd.remote_allowed),
            hiring_manager = COALESCE(p_hiring_manager, jd.hiring_manager),
            openings = COALESCE(p_openings, jd.openings),
            dossier_id = COALESCE(p_dossier_id, jd.dossier_id),
            level = COALESCE(p_level, jd.level),
            reporting_to = COALESCE(p_reporting_to, jd.reporting_to),
            updated_at = now()
        WHERE jd.jd_id = p_jd_id
        RETURNING *;

    ----------------------------------------------------------------
    -- MODE 4 = DELETE DATA BY JD_ID
    ----------------------------------------------------------------
    ELSIF p_mode = 4 THEN
        RETURN QUERY
        DELETE FROM public.job_description jd
        WHERE jd.jd_id = p_jd_id
        RETURNING *;

    ELSE
        RAISE EXCEPTION 'Invalid mode. Use 1=GET, 2=INSERT, 3=UPDATE, 4=DELETE';
    END IF;

END;
$function$
;
