from pydantic import BaseModel


class TailoredCVContent(BaseModel):
    company_name: str
    job_title: str
    tailored_summary: str
    key_skills: list[str]
    tailored_bullet_points: list[str]
    cover_letter_paragraph: str