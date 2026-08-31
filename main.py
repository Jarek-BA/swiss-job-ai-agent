import smtplib
import re
import sqlite3
import imaplib
import email
from html import escape
from email.header import decode_header
from urllib.parse import urlsplit, urlunsplit
from typing import List
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from pydantic import BaseModel
from google import genai
from google.genai import types

import config

MAX_JOBS_PER_BATCH = 15
MAX_SCREENING_BATCH = 30
SCREENING_THRESHOLD = 60
MAX_DESCRIPTION_CHARS = 2500
DATABASE_PATH = Path(__file__).with_name("jobs.sqlite3")
EMAIL_TEMPLATE_PATH = Path(__file__).with_name("email_template.html")
JOB_CATEGORIES = (
    "QA & Testing",
    "Audit & Compliance",
    "Sachbearbeitung & Kaufmännisch",
    "Business Support, Sales Ops & Data",
)

def clean_job_text(text):
    text = re.sub(r"\bContract type:\s*Permanent position\b", "", text, flags=re.I)
    text = re.sub(r"\bNew\s+Is this job relevant to you\?", "", text, flags=re.I)
    text = re.sub(r"Is this job relevant to you\?", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def clean_jobs_ch_title(title):
    title = re.sub(r"^\s*(?:Today|Yesterday|\d+\s+hours?\s+ago)\s*", "", title, flags=re.I)
    title = re.split(r"\s+Place of work:\s*", title, maxsplit=1, flags=re.I)[0]
    return title.strip()

def parse_jobs_ch_alert_metadata(text):
    text = re.sub(r"\s+", " ", text).strip()
    metadata = re.search(
        r"\bPlace of work\s*:\s*(.*?)\s+Workload\s*:", text, flags=re.I
    )
    if not metadata:
        return clean_jobs_ch_title(text), "", ""

    title = clean_jobs_ch_title(text[:metadata.start()])
    location = metadata.group(1).strip()
    company_match = re.search(
        r"\bContract type\s*:\s*(?:Permanent|Temporary)\s+position\s*"
        r"(.*?)(?=\s+(?:Easy apply|New|Is this job relevant)|$)",
        text[metadata.end():],
        flags=re.I,
    )
    company = company_match.group(1).strip() if company_match else ""
    if location and title.lower().endswith(location.lower()):
        title = title[: -len(location)].rstrip(" ,-/")
    return title, company, location

def normalise_jobs_ch_alert_job(job):
    title, company, location = parse_jobs_ch_alert_metadata(job["title"])
    normalised = dict(job)
    normalised["title"] = title
    normalised["company"] = job.get("company") or company
    normalised["location"] = job.get("location") or location
    return normalised

# Pydantic modely pro dávkové vyhodnocení
class SingleJobEvaluation(BaseModel):
    job_index: int
    is_relevant: bool
    match_score: int
    job_title: str
    company: str
    location: str
    pros: list[str]
    cons_or_gaps: str
    summary: str

class BatchJobEvaluation(BaseModel):
    evaluations: List[SingleJobEvaluation]

class ScreeningEvaluation(BaseModel):
    job_index: int
    is_potential_match: bool
    match_score: int

class BatchScreeningEvaluation(BaseModel):
    evaluations: List[ScreeningEvaluation]

def initialise_database():
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                link TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'jobs.ch',
                company TEXT,
                location TEXT,
                posted_at TEXT,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'discovered',
                screening TEXT,
                evaluation TEXT,
                fallback_notified_at TEXT,
                discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                evaluated_at TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS processed_emails (
                mailbox TEXT NOT NULL,
                uid TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (mailbox, uid)
            )
        """)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
        if "screening" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN screening TEXT")
        if "fallback_notified_at" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN fallback_notified_at TEXT")
        for column, definition in (("source", "TEXT NOT NULL DEFAULT 'jobs.ch'"),
                                   ("company", "TEXT"), ("location", "TEXT"),
                                   ("posted_at", "TEXT")):
            if column not in columns:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
        rows = connection.execute(
            "SELECT link, title, company, location FROM jobs "
            "WHERE source = 'jobs.ch' AND title LIKE '%Place of work%'"
        ).fetchall()
        for link, title, company, location in rows:
            parsed_title, parsed_company, parsed_location = parse_jobs_ch_alert_metadata(title)
            connection.execute(
                "UPDATE jobs SET title = ?, company = COALESCE(NULLIF(company, ''), ?), "
                "location = COALESCE(NULLIF(location, ''), ?), "
                "fallback_notified_at = NULL WHERE link = ?",
                (parsed_title, parsed_company, parsed_location, link),
            )

def save_discovered_jobs(jobs):
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO jobs (link, title, source) VALUES (?, ?, ?)",
            [(job["link"], job["title"], job.get("source", "jobs.ch")) for job in jobs],
        )

def save_alert_jobs(jobs):
    jobs = [
        normalise_jobs_ch_alert_job(job) if job.get("source", "jobs.ch") == "jobs.ch" else job
        for job in jobs
    ]
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executemany(
                        """INSERT OR IGNORE INTO jobs
                             (link, title, source, company, location, posted_at, description, status)
                             VALUES (?, ?, ?, ?, ?, ?, ?, 'ready')
               ON CONFLICT(link) DO UPDATE SET
                   title = CASE WHEN excluded.title != '' THEN excluded.title ELSE jobs.title END,
                                     source = excluded.source,
                                     company = COALESCE(excluded.company, jobs.company),
                                     location = COALESCE(excluded.location, jobs.location),
                                     posted_at = COALESCE(excluded.posted_at, jobs.posted_at),
                   description = CASE WHEN jobs.description IS NULL OR jobs.description = ''
                                      THEN excluded.description ELSE jobs.description END""",
                        [(job["link"], job["title"], job.get("source", "jobs.ch"),
                            job.get("company"), job.get("location"), job.get("posted_at"),
                            job["description"]) for job in jobs],
        )

def email_was_processed(mailbox, uid):
    with sqlite3.connect(DATABASE_PATH) as connection:
        return connection.execute(
            "SELECT 1 FROM processed_emails WHERE mailbox = ? AND uid = ?",
            (mailbox, uid),
        ).fetchone() is not None

def mark_email_processed(mailbox, uid):
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO processed_emails (mailbox, uid) VALUES (?, ?)",
            (mailbox, uid),
        )

def move_email_to_processed_folder(mailbox, uid):
    folder = config.LINKEDIN_PROCESSED_FOLDER
    result, _ = mailbox.select(folder, readonly=False)
    if result != "OK":
        create_result, _ = mailbox.create(folder)
        if create_result not in {"OK", "ALREADYEXISTS"}:
            raise RuntimeError(f"Could not create mailbox folder: {folder}")
    mailbox.select("INBOX", readonly=False)
    result, _ = mailbox.uid("COPY", uid, folder)
    if result != "OK":
        raise RuntimeError(f"Could not move alert UID {uid} to {folder}")
    result, _ = mailbox.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
    if result != "OK":
        raise RuntimeError(f"Could not delete original alert UID {uid}")
    mailbox.expunge()

def get_pending_jobs():
    return get_jobs_by_status("discovered", "details_failed")

def get_ready_jobs():
    return get_jobs_by_status("ready")

def get_screened_jobs():
    return get_jobs_by_status("screened")

def get_jobs_by_status(*statuses):
    placeholders = ",".join("?" for _ in statuses)
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT link, title, source, company, location, posted_at, description, status, screening FROM jobs "
            f"WHERE status IN ({placeholders}) ORDER BY discovered_at",
            statuses,
        ).fetchall()
    return [dict(row) for row in rows]

def get_fallback_jobs():
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT link, title, source, company, location, posted_at, discovered_at, description, status FROM jobs "
            "WHERE status != 'emailed' AND fallback_notified_at IS NULL "
            "ORDER BY discovered_at"
        ).fetchall()
    return [dict(row) for row in rows]

def mark_fallback_notified(jobs):
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executemany(
            "UPDATE jobs SET fallback_notified_at = CURRENT_TIMESTAMP WHERE link = ?",
            [(job["link"],) for job in jobs],
        )

def save_job_description(job, description):
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            "UPDATE jobs SET description = ?, status = 'ready' WHERE link = ?",
            (description, job["link"]),
        )

def mark_details_failed(job):
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            "UPDATE jobs SET status = 'details_failed' WHERE link = ?",
            (job["link"],),
        )

def save_evaluations(jobs, batch_eval):
    with sqlite3.connect(DATABASE_PATH) as connection:
        for eval_item in batch_eval.evaluations:
            index = eval_item.job_index - 1
            if 0 <= index < len(jobs):
                connection.execute(
                    "UPDATE jobs SET status = 'evaluated', evaluation = ?, "
                    "evaluated_at = CURRENT_TIMESTAMP WHERE link = ?",
                    (eval_item.model_dump_json(), jobs[index]["link"]),
                )

def save_screening(jobs, batch_screening):
    with sqlite3.connect(DATABASE_PATH) as connection:
        for screening in batch_screening.evaluations:
            index = screening.job_index - 1
            if 0 <= index < len(jobs):
                status = "screened" if screening.is_potential_match else "rejected"
                connection.execute(
                    "UPDATE jobs SET status = ?, screening = ? WHERE link = ?",
                    (status, screening.model_dump_json(), jobs[index]["link"]),
                )

def mark_emailed(jobs):
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executemany(
            "UPDATE jobs SET status = 'emailed' WHERE link = ?",
            [(job["link"],) for job in jobs],
        )

def get_evaluated_matches():
    matches = []
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT link, title, description, evaluation FROM jobs "
            "WHERE status = 'evaluated'"
        ).fetchall()
    for row in rows:
        evaluation = SingleJobEvaluation.model_validate_json(row["evaluation"])
        if evaluation.is_relevant and evaluation.match_score >= 70:
            matches.append((dict(row), evaluation))
    return matches

def decode_email_header(value):
    if not value:
        return ""
    parts = decode_header(value)
    return "".join(
        part.decode(encoding or "utf-8", errors="replace") if isinstance(part, bytes) else part
        for part, encoding in parts
    )

def extract_email_text(message):
    bodies = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/html":
            text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        bodies.append(text)
    return clean_job_text(" ".join(bodies))

def extract_email_links(message):
    links = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_type() != "text/html":
            continue
        payload = part.get_payload(decode=True)
        if payload:
            html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            links.extend(anchor.get("href", "") for anchor in soup.find_all("a", href=True))
    return links

def extract_email_job_links(message):
    jobs = []
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_type() != "text/html":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if re.search(r"linkedin\.com/(?:comm/)?jobs/view/", href, re.I):
                jobs.append((canonicalise_link(href), anchor.get_text(" ", strip=True)))
    return jobs

def linkedin_metadata(job_links, link):
    candidates = [title for job_link, title in job_links if job_link == link and title]
    short_title = next((title for title in candidates if " · " not in title), "")
    rich_title = next((title for title in candidates if " · " in title), "")
    title = short_title or (rich_title.split(" · ", 1)[0] if rich_title else "")
    company = ""
    location = ""
    if rich_title:
        details = rich_title[len(short_title):].strip() if short_title and rich_title.startswith(short_title) else rich_title
        parts = details.split(" · ", 1)
        company = parts[0].strip()
        location = parts[1].replace(" Actively recruiting", "").strip() if len(parts) > 1 else ""
    return title, company, location

def extract_jobs_ch_alert_links(message):
    jobs_by_link = {}
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_type() != "text/html":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if re.search(r"(?:www\.)?jobs\.ch/[a-z]{2}/vacancies/detail/", href, re.I):
                link = canonicalise_link(href)
                title = anchor.get_text(" ", strip=True)
                row = anchor.find_parent("tr")
                row_text = row.get_text("|", strip=True) if row else title
                fields = [field.strip() for field in row_text.split("|") if field.strip()]
                if fields:
                    title = max([title, *fields], key=len)
                title, company, location = parse_jobs_ch_alert_metadata(title)
                if not company and len(fields) >= 2:
                    company_location = fields[-1]
                    if "," in company_location:
                        company, location = [part.strip() for part in company_location.rsplit(",", 1)]
                candidate = (title, company, location)
                if link not in jobs_by_link or len(title) > len(jobs_by_link[link][0]):
                    jobs_by_link[link] = candidate
    return list(jobs_by_link.items())

def canonicalise_link(link):
    parts = urlsplit(link)
    path = parts.path.replace("/comm/jobs/", "/jobs/").rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))

def import_linkedin_alerts():
    if not config.LINKEDIN_ALERT_EMAIL or not config.LINKEDIN_ALERT_PASSWORD:
        return 0

    imported = 0
    mailbox_name = config.LINKEDIN_ALERT_EMAIL
    print("📬 Reading LinkedIn alert emails...")
    with imaplib.IMAP4_SSL("imap.gmail.com") as mailbox:
        mailbox.login(mailbox_name, config.LINKEDIN_ALERT_PASSWORD)
        mailbox.select("INBOX", readonly=False)
        result, data = mailbox.uid(
            "search", None, "UNSEEN", "FROM", "jobalerts-noreply@linkedin.com"
        )
        if result != "OK":
            raise RuntimeError("Could not search the LinkedIn alert mailbox")

        for uid_bytes in data[0].split():
            uid = uid_bytes.decode("ascii")
            if email_was_processed(mailbox_name, uid):
                continue
            result, message_data = mailbox.uid("fetch", uid, "(RFC822)")
            if result != "OK":
                continue
            raw_message = next(
                (item[1] for item in message_data if isinstance(item, tuple)), None
            )
            if not raw_message:
                continue
            message = email.message_from_bytes(raw_message)
            text = extract_email_text(message)
            email_links = extract_email_links(message)
            job_links = extract_email_job_links(message)
            links = {
                canonicalise_link(link)
                for link in re.findall(
                    r"https?://[^\s<>\"']*linkedin\.com/(?:comm/)?jobs/(?:view|search)[^\s<>\"']*",
                    text + " " + " ".join(email_links),
                )
            }
            jobs = [
                {
                    "link": link,
                    "title": linkedin_metadata(job_links, link)[0]
                        or decode_email_header(message.get("Subject")) or "LinkedIn job alert",
                    "source": "linkedin",
                    "company": linkedin_metadata(job_links, link)[1],
                    "location": linkedin_metadata(job_links, link)[2],
                    "description": text[:MAX_DESCRIPTION_CHARS],
                }
                for link in links
                if "/jobs/view/" in link
            ]
            save_alert_jobs(jobs)
            move_email_to_processed_folder(mailbox, uid)
            mark_email_processed(mailbox_name, uid)
            imported += len(jobs)
    return imported

def import_jobs_ch_alerts():
    if not config.LINKEDIN_ALERT_EMAIL or not config.LINKEDIN_ALERT_PASSWORD:
        return 0

    imported = 0
    mailbox_name = config.LINKEDIN_ALERT_EMAIL
    print("📬 Reading Jobs.ch alert emails...")
    with imaplib.IMAP4_SSL("imap.gmail.com") as mailbox:
        mailbox.login(mailbox_name, config.LINKEDIN_ALERT_PASSWORD)
        mailbox.select("INBOX", readonly=False)
        result, data = mailbox.uid(
            "search", None, "UNSEEN", "FROM", config.JOBS_CH_ALERT_SENDER
        )
        if result != "OK":
            raise RuntimeError("Could not search the Jobs.ch alert mailbox")

        for uid_bytes in data[0].split():
            uid = uid_bytes.decode("ascii")
            if email_was_processed(mailbox_name, uid):
                continue
            result, message_data = mailbox.uid("fetch", uid, "(RFC822)")
            if result != "OK":
                continue
            raw_message = next(
                (item[1] for item in message_data if isinstance(item, tuple)), None
            )
            if not raw_message:
                continue
            message = email.message_from_bytes(raw_message)
            text = extract_email_text(message)
            job_links = extract_jobs_ch_alert_links(message)
            unique_jobs = list(dict.fromkeys(job_links))
            jobs = [
                {
                    "link": link,
                    "title": title or decode_email_header(message.get("Subject")) or "Jobs.ch job alert",
                    "source": "jobs.ch",
                    "company": company,
                    "location": location,
                    "description": text[:MAX_DESCRIPTION_CHARS],
                }
                for link, (title, company, location) in unique_jobs
            ]
            save_alert_jobs(jobs)
            move_email_to_processed_folder(mailbox, uid)
            mark_email_processed(mailbox_name, uid)
            imported += len(jobs)
    return imported

def fetch_job_detail_page(page, job_url):
    """Extracts description text from detail page."""
    try:
        page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
        soup = BeautifulSoup(page.content(), "html.parser")

        content = soup.find("main") or soup.find("article") or soup
        for element in content.find_all(["script", "style", "nav", "footer"]):
            element.decompose()

        paragraphs = content.find_all(["p", "li", "h1", "h2", "h3"])
        text = " ".join(element.get_text(" ", strip=True) for element in paragraphs)
        return clean_job_text(text)[:MAX_DESCRIPTION_CHARS]
    except Exception as e:
        print(f"   ⚠️ Could not fetch detail: {e}")
        return ""

def evaluate_jobs_batch(client: genai.Client, jobs_list: list) -> BatchJobEvaluation:
    """Evaluates ALL jobs in 1 SINGLE API call to stay within daily quotas."""
    formatted_jobs_text = ""
    for idx, job in enumerate(jobs_list, start=1):
        formatted_jobs_text += f"\n--- JOB [{idx}] ---\n"
        formatted_jobs_text += f"Title: {job['title']}\n"
        formatted_jobs_text += f"Description: {job['description']}\n"

    prompt = f"""
    You are an expert Swiss career advisor. Evaluate the following {len(jobs_list)} job listings for the candidate.

    CANDIDATE PROFILE:
    {config.CANDIDATE_PROFILE}

    PREFERENCES & CONSTRAINTS:
    {config.CANDIDATE_PREFERENCES}

    LISTINGS:
    {formatted_jobs_text}
    """

    system_instruction = (
        "Evaluate each job listing independently and return an array for ALL jobs provided. "
        "Ensure job_index maps strictly to [1], [2], etc. Calibrate scores consistently: "
        "consider role fit, transferable experience, workload, location, language, and exclusions. "
        "For scores of 85 or higher, write a concrete 2-3 sentence summary, provide 3-5 specific "
        "pros tied to the listing and candidate profile, and name the most important risks or gaps. "
        "For lower scores, keep the summary and pros concise but still evidence-based."
    )

    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=BatchJobEvaluation,
            system_instruction=system_instruction
        ),
    )
    return BatchJobEvaluation.model_validate_json(response.text)

def evaluate_jobs_screening(client: genai.Client, jobs_list: list) -> BatchScreeningEvaluation:
    listings = "".join(
        f"\n--- JOB [{index}] ---\nTitle: {job['title']}\nDescription: {job['description']}\n"
        for index, job in enumerate(jobs_list, start=1)
    )
    prompt = f"""
    Screen these {len(jobs_list)} Swiss job listings against the candidate profile.
    Return one result for every job. Mark a job as a potential match when it may satisfy
    the role, location, workload, language, and exclusion preferences. Use a score from 0 to 100.

    CANDIDATE PROFILE:
    {config.CANDIDATE_PROFILE}

    PREFERENCES:
    {config.CANDIDATE_PREFERENCES}

    LISTINGS:
    {listings}
    """
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=BatchScreeningEvaluation,
            system_instruction=(
                "Return exactly one screening result per listing. Keep this pass concise; "
                "do not provide explanations. Preserve the job indexes."
            ),
        ),
    )
    return BatchScreeningEvaluation.model_validate_json(response.text)

def categorise_job(title):
    title = title.lower()
    if any(term in title for term in ("test", "qa", "quality assurance")):
        return "QA & Testing"
    if any(term in title for term in ("audit", "auditor", "compliance", "revisor")):
        return "Audit & Compliance"
    if any(term in title for term in ("sales", "business", "data", "application support", "operations")):
        return "Business Support, Sales Ops & Data"
    if any(term in title for term in ("sachbear", "kaufmänn", "administr", "rechnung")):
        return "Sachbearbeitung & Kaufmännisch"
    return "Business Support, Sales Ops & Data"

def render_email(template_subject, summary, sections):
    template = EMAIL_TEMPLATE_PATH.read_text(encoding="utf-8")
    return (template
            .replace("{{SUBJECT}}", escape(template_subject))
            .replace("{{SUMMARY}}", escape(summary))
            .replace("{{JOB_SECTIONS}}", sections))

def send_html_email(subject, body):
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = config.SENDER_EMAIL
    msg['To'] = config.RECEIVER_EMAIL
    msg.attach(MIMEText(body, "html", "utf-8"))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
        server.send_message(msg)

def sort_matches(jobs_with_eval):
    return sorted(
        jobs_with_eval,
        key=lambda item: item[1].match_score,
        reverse=True,
    )

def send_email(jobs_with_eval):
    jobs_with_eval = sort_matches(jobs_with_eval)
    sections = []
    grouped = {category: [] for category in JOB_CATEGORIES}
    for job, eval_data in jobs_with_eval:
        grouped[categorise_job(eval_data.job_title)].append((job, eval_data))
    for category in JOB_CATEGORIES:
        entries = grouped[category]
        if not entries:
            continue
        cards = []
        for job, eval_data in entries:
            pros = "".join(f"<li>{escape(pro)}</li>" for pro in eval_data.pros)
            cards.append(f"""
            <div class="job">
              <div class="job-title"><a href="{escape(job['link'], quote=True)}">{escape(eval_data.job_title)}</a></div>
              <div class="job-meta">{escape(eval_data.company)} | {escape(eval_data.location)} | <span class="score">{eval_data.match_score}% match</span></div>
              <p><span class="label">Summary:</span> {escape(eval_data.summary)}</p>
              <p><span class="label">Why it fits:</span></p><ul>{pros}</ul>
              <p><span class="label">Risks / gaps:</span> {escape(eval_data.cons_or_gaps)}</p>
            </div>""")
        sections.append(f"<h2>{escape(category)} ({len(entries)})</h2>{''.join(cards)}")
    subject = f"Swiss Job AI Agent: {len(jobs_with_eval)} matched job(s)"
    summary = (
        "These are the new job postings retrieved from jobs.ch and LinkedIn. "
        f"A total of {len(jobs_with_eval)} job(s) were found."
    )
    body = render_email(subject, summary, "".join(sections))
    send_html_email(subject, body)

def send_fallback_email(jobs):
    grouped = {category: [] for category in JOB_CATEGORIES}
    for job in jobs:
        grouped[categorise_job(job["title"])].append(job)
    sections = []
    for category in JOB_CATEGORIES:
        entries = grouped[category]
        if not entries:
            continue
        cards = []
        for job in entries:
            cards.append(f"""
            <div class="job">
              <div class="job-title"><a href="{escape(job['link'], quote=True)}">{escape(job['title'])}</a></div>
                            <div class="job-meta">Source: {escape(job.get('source') or 'Unknown')} | Company: {escape(job.get('company') or 'Not provided')} | Location: {escape(job.get('location') or 'Not provided')} | Posted: {escape(job.get('posted_at') or job.get('discovered_at') or 'Unknown')}</div>
            </div>""")
        sections.append(f"<h2>{escape(category)} ({len(entries)})</h2>{''.join(cards)}")
    subject = f"Swiss Job AI Agent: fallback job list ({len(jobs)} postings)"
    summary = (
        "These are the new job postings retrieved from jobs.ch and LinkedIn. "
        f"A total of {len(jobs)} job(s) were found. "
        "AI evaluation was unavailable, so this is the complete structured list."
    )
    body = render_email(subject, summary, "".join(sections))
    send_html_email(subject, body)

def main():
    if config.AI_ENABLED and not config.GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY environment variable missing.")
        return
    if config.AI_ENABLED and not config.CANDIDATE_PROFILE:
        print("❌ Error: CANDIDATE_PROFILE environment variable missing.")
        return
    if config.AI_ENABLED and not config.CANDIDATE_PREFERENCES:
        print("❌ Error: CANDIDATE_PREFERENCES environment variable missing.")
        return

    client = genai.Client(api_key=config.GEMINI_API_KEY) if config.AI_ENABLED else None
    initialise_database()

    print(f"🤖 AI evaluation: {'enabled' if config.AI_ENABLED else 'disabled'}")

    try:
        imported_alerts = import_linkedin_alerts()
        if imported_alerts:
            print(f"   Imported {imported_alerts} LinkedIn alert posting(s).")
        imported_jobs_ch = import_jobs_ch_alerts()
        if imported_jobs_ch:
            print(f"   Imported {imported_jobs_ch} Jobs.ch alert posting(s).")
    except Exception as e:
        print(f"❌ Alert mailbox error; continuing with other sources: {e}")

    pending_jobs = get_pending_jobs()
    ready_jobs = get_ready_jobs()
    screened_jobs = get_screened_jobs()
    print(f"📡 Email alerts queued {len(pending_jobs) + len(ready_jobs) + len(screened_jobs)} listings; "
          f"{len(pending_jobs)} need details, "
          f"{len(ready_jobs)} need screening, {len(screened_jobs)} await detailed evaluation.")

    if not pending_jobs and not ready_jobs and not screened_jobs:
        matches = get_evaluated_matches()
        if matches:
            send_email(matches)
            mark_emailed([job for job, _ in matches])
            print(f"✅ Success: Email sent with {len(matches)} position(s)!")
        else:
            fallback_jobs = get_fallback_jobs()
            if fallback_jobs:
                send_fallback_email(fallback_jobs)
                mark_fallback_notified(fallback_jobs)
                print(f"ℹ️ Fallback email sent with {len(fallback_jobs)} posting(s).")
            else:
                print("ℹ️ No new postings to process.")
        return

    if not config.AI_ENABLED:
        fallback_jobs = get_fallback_jobs()
        if fallback_jobs:
            try:
                send_fallback_email(fallback_jobs)
                mark_fallback_notified(fallback_jobs)
                print(f"ℹ️ AI disabled: fallback email sent with {len(fallback_jobs)} posting(s).")
            except Exception as e:
                print(f"❌ Fallback email error; postings remain available: {e}")
        else:
            print("ℹ️ AI disabled: no unnotified postings to send.")
        return

    print(f"\n📄 Step 2: Fetching details for {len(pending_jobs)} new postings...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        try:
            page = context.new_page()
            for job in pending_jobs:
                desc = fetch_job_detail_page(page, job['link'])
                if desc:
                    job['description'] = desc
                    save_job_description(job, desc)
                else:
                    mark_details_failed(job)
        finally:
            browser.close()

    ready_jobs = get_ready_jobs()
    print(f"\n⚡ Step 3: Screening {len(ready_jobs)} postings in batches of {MAX_SCREENING_BATCH}...")
    for start in range(0, len(ready_jobs), MAX_SCREENING_BATCH):
        batch = ready_jobs[start:start + MAX_SCREENING_BATCH]
        try:
            screening = evaluate_jobs_screening(client, batch)
            save_screening(batch, screening)
            print(f"   Screened batch of {len(batch)} postings.")
        except Exception as e:
            print(f"❌ Screening error; keeping remaining postings for retry: {e}")
            break

    screened_jobs = get_screened_jobs()
    detailed_jobs = []
    for job in screened_jobs:
        screening = ScreeningEvaluation.model_validate_json(job["screening"])
        if screening.match_score >= SCREENING_THRESHOLD:
            detailed_jobs.append(job)

    print(f"\n🧠 Step 4: Detailed evaluation for {len(detailed_jobs)} potential matches...")
    for start in range(0, len(detailed_jobs), MAX_JOBS_PER_BATCH):
        batch = detailed_jobs[start:start + MAX_JOBS_PER_BATCH]
        try:
            batch_eval = evaluate_jobs_batch(client, batch)
            save_evaluations(batch, batch_eval)
            print(f"   Evaluated batch of {len(batch)} postings.")
        except Exception as e:
            print(f"❌ Detailed AI error; keeping remaining postings for retry: {e}")
            break

    matches = get_evaluated_matches()
    print("\n----------------------------------------")
    if matches:
        try:
            send_email(matches)
            mark_emailed([job for job, _ in matches])
            print(f"✅ Success: Email sent with {len(matches)} position(s)!")
        except Exception as e:
            print(f"❌ Email error; matches remain queued for retry: {e}")
    else:
        fallback_jobs = get_fallback_jobs()
        if fallback_jobs:
            try:
                send_fallback_email(fallback_jobs)
                mark_fallback_notified(fallback_jobs)
                print(f"ℹ️ Fallback email sent with {len(fallback_jobs)} posting(s).")
            except Exception as e:
                print(f"❌ Fallback email error; postings remain available: {e}")
        else:
            print("ℹ️ Finished: No matches with score >= 70%.")

if __name__ == "__main__":
    main()