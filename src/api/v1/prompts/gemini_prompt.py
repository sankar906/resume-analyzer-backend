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


# Candidate eval (POST /candidates): JD context + resume PDF → structured JSON (see CandidatesEvalOutput).
CANDIDATES_EVAL_PROMPT = """
You are an expert technical recruiter. Evaluate the candidate's resume against the job
description below.

---
JOB DESCRIPTION:
{job_context}
---

The candidate's resume is attached as a PDF. Read the entire document carefully —
work experience, projects, and listed skills — before scoring anything.

EXTRACTION RULES:
- Extract candidate_name, phone, email, years_of_experience, and present_role.
- Use null for any field not found in the resume.
- years_of_experience must be a number (e.g. 4.5), not a string.

EVALUATION RULES:
- Evaluate ONLY sections listed under "Requirements:" in the JD. Use EXACT section titles as keys.
- For each requirement row output: skill, expected, candidate, rating.
- If the JD targets freshers or entry-level, evaluate based on projects and declared skills;
  internships are a strong positive signal.
- Cross-reference: work experience (strongest) → projects → declared skills.

  Levels (lowercase), relative to the candidate's experience stage:
    awareness    → referenced, no usage evidence (very low)
    basic        → coursework or minor exposure (low)
    intermediate → applied in projects; limited professional use
    advanced     → professional/production use with clear impact
    expert       → led or architected; deep domain ownership

  A less experienced candidate can reach "intermediate" or "advanced" through strong
  project evidence. Reserve "expert" for clear depth or leadership regardless of years.

  rating (1–100): 90–100 meets/exceeds · 75–90 one level below · 40–74 two levels below ·
  10–39 limited evidence · 1–9 no evidence

- Do NOT include rows or sections from outside the "Requirements:" block.
- Do NOT omit any row from any requirements table.
- Do NOT add extra keys beyond those specified.

FINAL ASSESSMENT:
  final_rating        : integer 0–100, overall fit score across all requirements
  final_verdict       : exactly one of — Strong Hire | Hire | Borderline | Reject
  final_justification : one concise sentence explaining the verdict

Output strictly valid JSON only. No markdown fences. No extra keys. No comments.
Schema:
{{
  "candidate_name": null,
  "phone": null,
  "email": null,
  "years_of_experience": null,
  "present_role": null,
  "evaluations": {{
    "<Exact Section Title>": [
      {{
        "skill": "",
        "expected": "",
        "candidate": "",
        "rating": 0
      }}
    ]
  }},
  "final_rating": 0,
  "final_verdict": "",
  "final_justification": ""
}}
"""
