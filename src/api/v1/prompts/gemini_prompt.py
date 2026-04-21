RESUME_PARSING_PROMPT = """
You are an expert HR assistant. Your task is to extract relevant information from the resume document provided (PDF above) and format it into a structured JSON format.
If a certain piece of information is missing from the resume, leave it as null or an empty list as appropriate.
"""


# Placeholders filled in llm_gemini._evaluate (EVALUATE_PROMPT.format).
EVALUATE_PROMPT = """
Task: Evaluate the provided resume against the job context below. Output a strict, objective assessment. Do not generate descriptive summaries or conversational text.

{job_context}

preference: experince, kowledgeares and technical skills, good to have certifications
Output strictly in JSON matching this structure:
{{
  "knowledge_areas": {{
    "rating": <0-100 score>,
    "reason": "<1-sentence evidence from resume. If missing, write 'No evidence found.'>"
  }},
  "technical_skills": {{
    "rating": <0-100 score>,
    "reason": "<1-sentence evidence from resume. If missing, write 'No evidence found.'>"
  }},
  "experience": {{
    "rating": <0-100 score>,
    "reason": "<1-sentence evidence from resume. If missing, write 'No evidence found.'>"
  }},
  "certifications": {{
    "rating": <0-100 score>,
    "reason": "<1-sentence evidence from resume. If missing, write 'No evidence found.'>"
  }},
  "final_rating": <0-100 overall score>,
  "final_verdict": "<Strong Hire / Average / Reject>",
  "final_justification": "<1-sentence justification>"
}}

Resume (candidate profile for evaluation):
{resume_text}
"""


# Resume PDF + job context → structured match (see llm_gemini._resume_job_match_pdf).
JOB_MATCH_PROMPT_SINGLE = """
You are an expert recruiter. The candidate's resume is attached as a PDF. Read it carefully.
You are given exactly one job posting below. Extract the candidate's contact details and current role from the resume, assess fit against this job, and respond in JSON only.
Allowed value for "preferred_job_role" (must match exactly, character for character):
{allowed_titles_block}

Job posting:
{job_contexts}

Rules:
- Copy name, email, phone, and currentrole from the resume PDF when present; use null only if not found.
- Set preferred_job_role to the allowed title above (there is only one).
- Give a concise final_verdict (e.g. Strong Hire / Average / Reject) and a one-sentence final_justification.
"""


JOB_MATCH_PROMPT_MULTI = """
You are an expert recruiter. The candidate's resume is attached as a PDF. Read it carefully.
Multiple job postings are listed below. Decide which single role this candidate fits best. Extract contact details and current role from the resume.
You MUST set "preferred_job_role" to exactly one of the allowed titles below (copy the title string exactly).

Allowed titles for preferred_job_role (choose exactly one):
{allowed_titles_block}

Job postings:
{job_contexts}

Rules:
- Copy name, email, phone, and currentrole from the resume PDF when present; use null only if not found.
- preferred_job_role must be exactly one of the allowed titles listed above.
- Give a concise final_verdict for that best-matching role and a one-sentence final_justification explaining why that role is the best match among the options.
"""


# Requirements-aligned eval: JD context + resume (PDF or text) → structured JSON (see RequirementsAlignedEvalOutput).
REQUIREMENTS_ALIGNED_EVAL_PROMPT = """
You are an expert recruiter. Evaluate the candidate against the job context below.

{job_context}

{resume_instruction}

Rules:
- Extract candidate_name, phone, email, years_of_experience, and present_role from the resume (PDF or text). Use null if missing.
- years_of_experience must be a JSON number (e.g. 4.5), not a string like "4+" or "5 years".
- Under "Requirements", for each section that appears in the job context (e.g. Technical skills, Core competencies), use that EXACT section title as a JSON key under "evaluations".
- For each row listed in the job requirement tables (each skill/subject line), output one object in the array for that section with: "skill" (subject text), "expected" (level or expectation from the JD), "candidate" (exactly one of these lowercase strings, based only on what the resume demonstrates for that skill: awareness, basic, intermediate, advanced, experience), "rating" (integer 1 to 100 for fit on that line). Do not put sentences or quotes in "candidate" — only one of the five level words.
- Include every requirement row from the job Requirements section; do not omit sections that appear in the job context.
- Omit sections that are not present in the job context, or that were not meant to be evaluated.
- final_rating: 0–100 overall. final_verdict: short string (e.g. Strong Hire / Average / Reject). final_justification: one sentence.

Output strictly JSON only, no markdown fences, with this top-level shape:
{{
  "candidate_name": null,
  "phone": null,
  "email": null,
  "years_of_experience": null,
  "present_role": null,
  "evaluations": {{ "Technical skills": [{{ "skill": "", "expected": "", "candidate": "intermediate", "rating": 0 }}] }},
  "final_rating": 0,
  "final_verdict": "",
  "final_justification": ""
}}
Use the evaluations structure as shown; repeat keys and array entries as needed for all sections and rows from the job Requirements.
"""
