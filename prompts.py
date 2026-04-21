RESUME_PARSING_PROMPT = """
You are an expert HR assistant. Your task is to extract relevant information from the provided resume text and format it into a structured JSON format.
If a certain piece of information is missing from the resume, leave it as null or an empty list as appropriate.

Resume Text:
{resume_text}
"""


EVALUATE_PROMPT = """
Role: Senior AI/ML Technical Recruiter & Resume Evaluator.

Task: Evaluate the provided resume for an AI/ML Engineer position against the provided Job Description. Do not generate descriptive summaries or conversational text. Output a strict, objective assessment mapping extracted resume evidence to the specific criteria below. 

Job Description:
Job Title: Data Analyst / AI/ML Engineer
We are looking for a candidate with strong Python and SQL skills. 
The candidate must have experience analyzing data, building visualizations, and deploying models.
A background in statistical foundations and machine learning concepts is highly required.

Evaluation Criteria:

Knowledge Areas:
1. Statistical Foundations
2. Machine Learning Concepts
3. Model Evaluation Metrics
4. Data Engineering Awareness

Technical Skills:
1. Programming Proficiency (Python / R)
2. SQL & Data Querying
3. Visualization & Storytelling
4. Deployment & Production Awareness
5. Model Building & Tuning

Output Format:
You MUST output strictly in JSON format matching the following structure:
{{
  "skills": {{
    "rating": <calculate overall 1-5 score based on Technical Skills and Knowledge Areas>,
    "reason": "<1-sentence extraction of matching evidence from resume. If missing, write 'No evidence found.'>"
  }},
  "experience": {{
    "rating": <calculate overall 1-5 score for past experience relevance>,
    "reason": "<1-sentence extraction of matching evidence from resume. If missing, write 'No evidence found.'>"
  }},
  "certifications": {{
    "rating": <calculate overall 1-5 score for relevant certifications>,
    "reason": "<1-sentence extraction of matching evidence from resume. If missing, write 'No evidence found.'>"
  }},
  "final_verdict": "<Strong Hire / Average / Reject>",
  "final_justification": "<1-sentence justification>"
}}

Resume Text:
{resume_text}
"""