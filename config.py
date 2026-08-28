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
LINKEDIN_ALERT_EMAIL = os.getenv("LINKEDIN_ALERT_EMAIL")
LINKEDIN_ALERT_PASSWORD = os.getenv("LINKEDIN_ALERT_PASSWORD")
LINKEDIN_PROCESSED_FOLDER = os.getenv("LINKEDIN_PROCESSED_FOLDER", "LinkedIn/Processed")
JOBS_CH_ALERT_SENDER = "jobmail@jobs.ch"

# Candidate Profile / Resume Data
WIFE_CV = """
CANDIDATE PROFILE: Lada Patakova
- Residence: Wetzikon, Canton Zurich, Switzerland (Work Permit C)
- Core Experience: Administration, Back Office Support, Sales Support, Invoice Processing, Master Data Maintenance, Quality Assurance, Software Testing, Financial Analysis, Internal Audit.
- Key Skills: MS Office (Advanced Excel), Document Management, Invoicing (Accounts Payable/Receivable), Order Processing.
- Languages:
  * English: C1 (Fluent / Full professional)
  * German: B2 (Professional working proficiency)
  * Czech: C2 (Native)
  * French: A2 (Basic)
- Personal Strengths: Highly reliable, structured, meticulous, customer-oriented, comfortable with digital tools and data.
"""

# Job Search Preferences & Constraints
WIFE_PREFERENCES = """
TARGET POSITIONS:
- Office Administrator / Sachbearbeiterin / Kaufmännische Angestellte / Auditorin
- Back Office Specialist / Administration & Support
- Sales Support / Order Management / Customer Service Support
- Junior Data Entry / Quality Assurance / Document Management Specialist
- Junior Financial Administrator / Billing Clerk

WORK SCHEDULE & LOCATION:
- Workload: 50% to 100% (Part-time or Full-time)
- Location: Canton Zurich (preferably accessible from Wetzikon ZH, e.g., Wetzikon, Uster, Hinwil, Pfäffikon, Zurich city) or Remote.

RULES & CONSTRAINTS:
- ACCEPTABLE ROLES: Any office/back-office, administrative, clerical, customer support, data entry, or light financial support roles.
- PREFERRED LANGUAGE: English is preferred, but German (B2 level) is fully acceptable and expected for most roles.
- EXCLUDE: Physical manual labor (warehouse, assembly line, cleaning) and gastronomy/hospitality roles.
- DEGREE NOTE: Do not require local Swiss diplomas or Swiss certifications; evaluate based on practical experience in office work, SAP, Excel, and administrative processes.
"""

# Swiss Job Portals RSS Feeds
# Note: You can expand this list with more RSS URLs or tailored search queries
RSS_FEEDS = [
    "https://www.jobs.ch/en/jobs/rss/?term=sachbearbeiter",
    "https://www.jobs.ch/en/jobs/rss/?term=administration",
    "https://www.jobs.ch/en/jobs/rss/?term=back%20office",
]