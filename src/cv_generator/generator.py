from google import genai
from google.genai import types

import config
from src.models.cv_schema import TailoredCVContent


def generate_cv_content(job_description: str) -> TailoredCVContent:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required to generate tailored CV content")
    if not config.CANDIDATE_PROFILE:
        raise RuntimeError("CANDIDATE_PROFILE is required to generate tailored CV content")
    if not config.CANDIDATE_CV_INPUT:
        raise RuntimeError("cv_input.md is required to generate tailored CV content")

    prompt = f"""
Create tailored CV content for this job description.

CANDIDATE PROFILE:
{config.CANDIDATE_PROFILE}

SOURCE CV CONTENT:
{config.CANDIDATE_CV_INPUT}

CANDIDATE PREFERENCES:
{config.CANDIDATE_PREFERENCES}

JOB DESCRIPTION:
{job_description}
"""
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TailoredCVContent,
            system_instruction=(
                "Re-frame and highlight only real achievements and skills from the candidate "
                "profile to match the job listing, including relevant SAP, audit, office "
                "administration, and language experience when present. Never invent employers, "
                "qualifications, metrics, responsibilities, or credentials. Keep the output "
                "specific, professional, and suitable for a one-page CV."
            ),
        ),
    )
    return TailoredCVContent.model_validate_json(response.text)