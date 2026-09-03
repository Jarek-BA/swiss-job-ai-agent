# Swiss Job AI Agent

An automated Swiss job scout for administrative and back-office roles in Canton Zurich. It collects job postings from jobs.ch, evaluates them against the candidate profile, and sends relevant matches by email.

## How It Works

1. Gmail IMAP reads new LinkedIn and jobs.ch alert emails.
2. Job URLs are deduplicated and stored in `jobs.sqlite3`.
3. New postings are opened once with Playwright and their detail text is saved locally and archived in Cloud Storage when configured.
4. Gemini performs a compact screening pass, up to 30 postings per request.
5. Only potential matches are sent to detailed evaluation, in batches of 15.
6. Matches scoring at least 70% are sent by email and marked as `emailed`, highest scores first.

The database prevents a posting from being processed repeatedly. Jobs that fail during scraping, AI evaluation, or email delivery remain queued for a later run.

## Email Output

The email layout is defined in `email_template.html`, separate from the scraping and AI code. Successful AI matches are grouped into four fixed categories: QA & Testing, Audit & Compliance, Sachbearbeitung & Kaufmännisch, and Business Support, Sales Ops & Data.

If AI evaluation is unavailable, the agent sends a fallback email containing every unnotified posting grouped under the same categories. Fallback notifications are tracked in SQLite and are not repeatedly sent on every run. All values inserted into the HTML are escaped before rendering.

## Setup

Create and activate the virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install Python dependencies and the Chromium browser used for AI detail-page enrichment:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Create a `.env` file in this directory, or clone the private `personal-ai-agent-config` repository beside this project. The app automatically loads `../personal-ai-agent-config/.env` and the Markdown files in `../personal-ai-agent-config/swiss-job-ai-agent/` when they exist. Set `PRIVATE_CONFIG_DIR` to use a different configuration directory.

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite
CANDIDATE_PROFILE=your_private_candidate_profile
CANDIDATE_PREFERENCES=your_private_candidate_preferences
LINKEDIN_ALERT_EMAIL=swiss.jobs.alerts@gmail.com
LINKEDIN_ALERT_PASSWORD=your_gmail_app_password
JOBS_CH_ALERT_SENDER=jobmail@jobs.ch
LINKEDIN_PROCESSED_FOLDER=LinkedIn/Processed
SENDER_EMAIL=your_gmail_address
SENDER_PASSWORD=your_gmail_app_password
RECEIVER_EMAIL=recipient_address
GOOGLE_CLOUD_PROJECT=your_google_cloud_project_id
JOB_ARCHIVE_BUCKET=your_private_bucket_name
```

For Gmail, `SENDER_PASSWORD` should be an App Password, not the normal account password.
The LinkedIn alert mailbox should also use a Gmail App Password. Enable IMAP for the mailbox if required by its Gmail settings.

## Run

Run from this directory with the virtual environment active:

```bash
python -u main.py
```

The first run may collect many postings and use several Gemini requests. Later runs skip URLs already stored in `jobs.sqlite3` and process only queued work.

To send a test email without changing the source mailbox, moving or labeling alert emails, updating the real SQLite database, or writing to Google Sheets, run:

```bash
python -u main.py --dry-run
```

Dry-run mode reads alert messages with IMAP `BODY.PEEK`, processes a temporary copy of the local database, skips mailbox moves and Google Sheets synchronization, and still sends the resulting email. The outgoing message itself may appear in the sender account's Sent folder.

## GitHub Actions

`.github/workflows/daily-job-agent.yml` runs the agent daily at 06:00 UTC. It can also be started manually from the **Actions** tab. Runs are serialized so two executions cannot update the SQLite queue at the same time.

Add these GitHub Actions Secrets under **Settings > Secrets and variables > Actions**:

```text
GEMINI_API_KEY
LINKEDIN_ALERT_EMAIL
LINKEDIN_ALERT_PASSWORD
SENDER_EMAIL
SENDER_PASSWORD
RECEIVER_EMAIL
PRIVATE_CONFIG_REPO_TOKEN
GOOGLE_SHEETS_CREDENTIALS_JSON
```

The workflow appends evaluated matches to the configured Google Sheet. Share the sheet with the service account email as an Editor, and store the downloaded service-account JSON as the `GOOGLE_SHEETS_CREDENTIALS_JSON` secret. Existing links are checked in column G before rows are appended. Column H (`Description Archive`) links to the private archived JSON in Google Cloud Console when available. Columns I-K (`Status`, `Applied Date`, and `Application Notes`) are left for manual updates in the sheet.

The workflow validates these secrets before running. An empty value is not reported to the log, but the job will stop with the missing-secret names and setup location.

Optional Actions Variables:

```text
GEMINI_MODEL
JOBS_CH_ALERT_SENDER
JOBS_CH_ALERT_SENDERS
LINKEDIN_PROCESSED_FOLDER
AI_ENABLED
```

`AI_ENABLED` accepts `yes` or `no`. Manual runs show a required **Run Gemini evaluation?** choice and default to `no`. Scheduled runs use the `AI_ENABLED` repository variable and default to `no` when it is not defined. With AI disabled, the workflow still imports alerts and sends the structured fallback email without requiring or calling Gemini.

Jobs.ch alerts are read from both `jobmail@jobs.ch` and `info@jobs.ch` by default. Set `JOBS_CH_ALERT_SENDERS` to a comma-separated list if the sender addresses change. Imported postings follow the same parsing, deduplication, AI evaluation, email, and Google Sheets tracking flow.

The local candidate profile and preferences are maintained as Markdown files in the private `personal-ai-agent-config/swiss-job-ai-agent/` repository. GitHub Actions checks out that repository using a read-only `PRIVATE_CONFIG_REPO_TOKEN`; candidate text does not need to be duplicated into GitHub Secrets. Do not commit private candidate data to this public repository.

Job descriptions are fetched from the actual posting page, not copied from the alert email, and archived as private JSON objects in Cloud Storage when `JOB_ARCHIVE_BUCKET` is configured. LinkedIn pages use their dedicated public description markup when available, excluding sign-in prompts and page chrome. The existing service-account JSON needs `roles/storage.objectAdmin` on that bucket. The default GitHub Actions bucket is `swiss_jobs_db`; set the `JOB_ARCHIVE_BUCKET` and `GOOGLE_CLOUD_PROJECT` repository variables if these differ. Objects are keyed by a SHA-256 hash of the canonical posting URL, so a later CV workflow can retrieve the description without scraping the posting again. Dry-run mode does not upload archive objects.

## Tailored CV Generation

`generate_cv.py` creates a tailored CV from a job URL or raw job-description text. Gemini uses the private candidate profile, preferences, and extracted source CV content to produce structured content without inventing qualifications. The default output is an editable Google Slides presentation copied from the configured master template; PDF output uses the private Jinja2 template and WeasyPrint.

Install the dependencies with `python -m pip install -r requirements.txt`, then configure these private values in `.env` or the private configuration repository:

```env
GOOGLE_SLIDES_TEMPLATE_ID=1RTmF2OYGzvkGjc_Zv3UexyJNbh3S9D_XCIaGsFYpcpk
GOOGLE_DRIVE_FOLDER_ID=your_target_folder_id_or_drive_folder_url
USER_EMAIL=your_personal_email
GOOGLE_SHEETS_CREDENTIALS_PATH=google-service-account.json
```

Store `cv_input.md` in `personal-ai-agent-config/swiss-job-ai-agent/` with the extracted content of the real CV. The service-account JSON must have access to the Slides template and target folder. `GOOGLE_DRIVE_FOLDER_ID` may be a folder ID or a full Drive folder URL. Generate a Google Slides presentation, PDF, or both:

```bash
python generate_cv.py --url "https://jobs.ch/..." --format both
python generate_cv.py --text "Job description..." --format pdf --output tailored-cv.pdf
```

Google Slides output replaces `{{COMPANY}}`, `{{JOB_TITLE}}`, `{{TAILORED_SUMMARY}}`, `{{KEY_SKILLS}}`, `{{EXPERIENCE_HIGHLIGHTS}}`, and `{{COVER_LETTER_INTRO}}` in the copied presentation and grants `USER_EMAIL` Editor access. The private PDF template is `personal-ai-agent-config/swiss-job-ai-agent/cv_template.html`. The generated PDF and service-account JSON are ignored by Git.

The workflow caches `jobs.sqlite3` between runs because GitHub-hosted runners are temporary. The cache is not a permanent backup; export or replace the persistence layer before relying on the history for long-term retention.

## Tests

Run the standard-library regression tests without making network, AI, or email requests:

```bash
python -m unittest discover -s tests -v
```

## Configuration

The candidate profile and preferences are loaded at runtime from `personal-ai-agent-config/swiss-job-ai-agent/candidate_profile.md` and `candidate_preferences.md`, with environment variables as a CI fallback. The Google Sheet ID and service-account key path are configured with `GOOGLE_SHEET_ID` and `GOOGLE_SHEETS_CREDENTIALS_PATH`. The batch sizes and score thresholds are defined in `main.py`; `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite` and can be changed in `.env` or GitHub Actions Variables.

LinkedIn and Jobs.ch alerts are read from the optional `LINKEDIN_ALERT_EMAIL` mailbox. The program searches only unseen messages from each alert sender, extracts job URLs, titles, and alert text, records message UIDs, and moves processed messages to `LINKEDIN_PROCESSED_FOLDER`. It does not log in to LinkedIn or scrape LinkedIn pages.

Playwright is used only to enrich alert postings with detail-page text when AI evaluation is enabled. Job discovery comes from the configured Gmail alerts.

## Local State

`jobs.sqlite3` contains discovered postings, extracted descriptions, screening results, detailed evaluations, and processing statuses. Back it up if the processing history should be preserved. Delete it only if all postings should be treated as new again.
