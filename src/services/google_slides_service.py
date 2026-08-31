from pathlib import Path

import config
from src.models.cv_schema import TailoredCVContent


SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive",
]


def _bullets(values: list[str]) -> str:
    return "\n".join(f"• {value}" for value in values)


def create_tailored_google_slides(content: TailoredCVContent) -> str:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    if not config.GOOGLE_SLIDES_TEMPLATE_ID:
        raise RuntimeError("GOOGLE_SLIDES_TEMPLATE_ID is required for Google Slides output")
    if not config.GOOGLE_DRIVE_FOLDER_ID:
        raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID is required for Google Slides output")
    if not config.USER_EMAIL:
        raise RuntimeError("USER_EMAIL is required for Google Slides output")

    credentials_path = Path(config.GOOGLE_SHEETS_CREDENTIALS_PATH)
    if not credentials_path.is_file():
        raise FileNotFoundError(f"Google service-account file not found: {credentials_path}")
    credentials = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
    drive = build("drive", "v3", credentials=credentials)
    slides = build("slides", "v1", credentials=credentials)
    name = f"CV - {content.company_name} - {content.job_title}"[:255]
    copied = drive.files().copy(
        fileId=config.GOOGLE_SLIDES_TEMPLATE_ID,
        body={"name": name, "parents": [config.GOOGLE_DRIVE_FOLDER_ID]},
    ).execute()
    presentation_id = copied["id"]

    replacements = {
        "{{COMPANY}}": content.company_name,
        "{{JOB_TITLE}}": content.job_title,
        "{{TAILORED_SUMMARY}}": content.tailored_summary,
        "{{KEY_SKILLS}}": _bullets(content.key_skills),
        "{{EXPERIENCE_HIGHLIGHTS}}": _bullets(content.tailored_bullet_points),
        "{{COVER_LETTER_INTRO}}": content.cover_letter_paragraph,
    }
    slides.presentations().batchUpdate(
        presentationId=presentation_id,
        body={
            "requests": [
                {"replaceAllText": {"containsText": {"text": tag, "matchCase": True}, "replaceText": value}}
                for tag, value in replacements.items()
            ]
        },
    ).execute()
    drive.permissions().create(
        fileId=presentation_id,
        body={"type": "user", "role": "writer", "emailAddress": config.USER_EMAIL},
        sendNotificationEmail=True,
    ).execute()
    return f"https://docs.google.com/presentation/d/{presentation_id}/edit"