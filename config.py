import os
from pathlib import Path
from dotenv import load_dotenv

# Load the reusable private configuration beside this repository when present.
default_config_dir = Path(__file__).resolve().parent.parent / "personal-ai-agent-config"
config_dir = Path(os.getenv("PRIVATE_CONFIG_DIR", str(default_config_dir)))
load_dotenv(config_dir / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")


def read_private_setting(filename):
	setting_file = config_dir / "swiss-job-ai-agent" / filename
	try:
		return setting_file.read_text(encoding="utf-8").strip()
	except FileNotFoundError:
		return ""

# API and Email Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
AI_ENABLED = os.getenv("AI_ENABLED", "no").strip().lower() in {"yes", "true", "1"}
LINKEDIN_ALERT_EMAIL = os.getenv("LINKEDIN_ALERT_EMAIL")
LINKEDIN_ALERT_PASSWORD = os.getenv("LINKEDIN_ALERT_PASSWORD")
LINKEDIN_PROCESSED_FOLDER = os.getenv("LINKEDIN_PROCESSED_FOLDER", "LinkedIn/Processed")
JOBS_CH_ALERT_SENDER = os.getenv("JOBS_CH_ALERT_SENDER", "jobmail@jobs.ch")
JOBS_CH_ALERT_SENDERS = tuple(dict.fromkeys(
	 sender.strip() for sender in os.getenv(
		"JOBS_CH_ALERT_SENDERS",
		f"{JOBS_CH_ALERT_SENDER},info@jobs.ch",
	).split(",") if sender.strip()
))

# Private candidate configuration is kept as human-readable Markdown files.
CANDIDATE_PROFILE = read_private_setting("candidate_profile.md")
CANDIDATE_PREFERENCES = read_private_setting("candidate_preferences.md")
CANDIDATE_CV_INPUT = read_private_setting("cv_input.md")
CANDIDATE_PROFILE = CANDIDATE_PROFILE or os.getenv("CANDIDATE_PROFILE", "").strip()
CANDIDATE_PREFERENCES = CANDIDATE_PREFERENCES or os.getenv("CANDIDATE_PREFERENCES", "").strip()
CANDIDATE_CV_INPUT = CANDIDATE_CV_INPUT or os.getenv("CANDIDATE_CV_INPUT", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1wm3GIHo1HGwYJfkU1Yotcg6wb_gKP3hlZMVkSYdTv-I")
GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "google-service-account.json")
GOOGLE_DOCS_TEMPLATE_ID = os.getenv("GOOGLE_DOCS_TEMPLATE_ID", "")
GOOGLE_SLIDES_TEMPLATE_ID = os.getenv(
	"GOOGLE_SLIDES_TEMPLATE_ID",
	"1RTmF2OYGzvkGjc_Zv3UexyJNbh3S9D_XCIaGsFYpcpk",
)
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
if "/folders/" in GOOGLE_DRIVE_FOLDER_ID:
	GOOGLE_DRIVE_FOLDER_ID = GOOGLE_DRIVE_FOLDER_ID.split("/folders/", 1)[1].split("?", 1)[0].rstrip("/")
USER_EMAIL = os.getenv("USER_EMAIL", "")
