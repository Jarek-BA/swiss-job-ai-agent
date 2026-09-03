import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import config


def _object_name(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    source = urlsplit(url).netloc or "unknown"
    return f"jobs/{source}/{digest}.json"


def _get_bucket():
    if not config.JOB_ARCHIVE_BUCKET:
        return None

    from google.cloud import storage
    from google.oauth2.service_account import Credentials

    credentials = Credentials.from_service_account_file(
        config.GOOGLE_SHEETS_CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
    )
    client = storage.Client(project=config.GOOGLE_CLOUD_PROJECT or None, credentials=credentials)
    return client.bucket(config.JOB_ARCHIVE_BUCKET)


def archive_job_description(job: dict, description: str) -> str:
    """Upload the latest cleaned description and return its private gs:// URI."""
    bucket = _get_bucket()
    if bucket is None or not description:
        return ""

    url = job["link"]
    object_name = _object_name(url)
    payload = {
        "schema_version": 1,
        "url": url,
        "source": job.get("source", "unknown"),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "posted_at": job.get("posted_at", ""),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "description_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest(),
    }
    blob = bucket.blob(object_name)
    blob.upload_from_string(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    return f"gs://{config.JOB_ARCHIVE_BUCKET}/{object_name}"


def load_archived_job_description(url: str) -> str:
    bucket = _get_bucket()
    if bucket is None:
        raise RuntimeError("JOB_ARCHIVE_BUCKET is not configured")

    blob = bucket.blob(_object_name(url))
    payload = json.loads(blob.download_as_text())
    return payload["description"]
