# Swiss Job AI Agent

An automated Swiss job scout for administrative and back-office roles in Canton Zurich. It collects job postings from jobs.ch, evaluates them against the candidate profile, and sends relevant matches by email.

## How It Works

1. Playwright opens up to five pages of the jobs.ch search results.
2. Job URLs are deduplicated and stored in `jobs.sqlite3`.
3. New postings are opened once and their detail text is saved locally.
4. Gemini performs a compact screening pass, up to 30 postings per request.
5. Only potential matches are sent to detailed evaluation, in batches of 15.
6. Matches scoring at least 70% are sent by email and marked as `emailed`.

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

Install Python dependencies and the Chromium browser used by Playwright:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Create a `.env` file in this directory:

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite
LINKEDIN_ALERT_EMAIL=swiss.jobs.alerts@gmail.com
LINKEDIN_ALERT_PASSWORD=your_gmail_app_password
LINKEDIN_PROCESSED_FOLDER=LinkedIn/Processed
SENDER_EMAIL=your_gmail_address
SENDER_PASSWORD=your_gmail_app_password
RECEIVER_EMAIL=recipient_address
```

For Gmail, `SENDER_PASSWORD` should be an App Password, not the normal account password.
The LinkedIn alert mailbox should also use a Gmail App Password. Enable IMAP for the mailbox if required by its Gmail settings.

## Run

Run from this directory with the virtual environment active:

```bash
python -u main.py
```

The first run may collect many postings and use several Gemini requests. Later runs skip URLs already stored in `jobs.sqlite3` and process only queued work.

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
```

Optional Actions Variables:

```text
GEMINI_MODEL
LINKEDIN_PROCESSED_FOLDER
```

The workflow caches `jobs.sqlite3` between runs because GitHub-hosted runners are temporary. The cache is not a permanent backup; export or replace the persistence layer before relying on the history for long-term retention.

## Tests

Run the standard-library regression tests without making network, AI, or email requests:

```bash
python -m unittest discover -s tests -v
```

## Configuration

The candidate profile, preferences, search URL, page limit, batch sizes, and score thresholds are defined in `config.py` and `main.py`. `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite` and can be changed in `.env`.

LinkedIn and Jobs.ch alerts are read from the optional `LINKEDIN_ALERT_EMAIL` mailbox. The program searches only unseen messages from each alert sender, extracts job URLs, titles, and alert text, records message UIDs, and moves processed messages to `LINKEDIN_PROCESSED_FOLDER`. It does not log in to LinkedIn or scrape LinkedIn pages.

The current jobs.ch scraper uses a hard-coded search URL. The `RSS_FEEDS` list in `config.py` is retained for future feed-based discovery but is not used by the current Playwright implementation.

## Local State

`jobs.sqlite3` contains discovered postings, extracted descriptions, screening results, detailed evaluations, and processing statuses. Back it up if the processing history should be preserved. Delete it only if all postings should be treated as new again.
