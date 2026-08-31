import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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

# Private candidate configuration. Set these in local .env or GitHub Actions Secrets.
CANDIDATE_PROFILE = os.getenv("CANDIDATE_PROFILE", "").strip()
CANDIDATE_PREFERENCES = os.getenv("CANDIDATE_PREFERENCES", "").strip()

# Swiss Job Portals RSS Feeds
# Note: You can expand this list with more RSS URLs or tailored search queries
RSS_FEEDS = [
    "https://www.jobs.ch/en/jobs/rss/?term=sachbearbeiter",
    "https://www.jobs.ch/en/jobs/rss/?term=administration",
    "https://www.jobs.ch/en/jobs/rss/?term=back%20office",
]