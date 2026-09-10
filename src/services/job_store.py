import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SQLiteJobStore:
    def __init__(self, database_path):
        self.database_path = Path(database_path)

    def connect(self):
        return sqlite3.connect(self.database_path)


class FirestoreJobStore:
    def __init__(self, project_id=None, credentials_path=None, collection="jobs"):
        from google.cloud import firestore
        from google.oauth2.service_account import Credentials

        credentials = Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/datastore"],
        ) if credentials_path else None
        self.client = firestore.Client(project=project_id or None, credentials=credentials)
        self.firestore = firestore
        self.jobs = self.client.collection(collection)
        self.processed_emails = self.client.collection("processed_emails")

    @staticmethod
    def _job_id(link):
        return hashlib.sha256(link.encode("utf-8")).hexdigest()

    @staticmethod
    def _email_id(mailbox, uid):
        return hashlib.sha256(f"{mailbox}\0{uid}".encode("utf-8")).hexdigest()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _commit_operations(self, operations):
        for start in range(0, len(operations), 400):
            batch = self.client.batch()
            for operation in operations[start:start + 400]:
                operation(batch)
            batch.commit()

    @staticmethod
    def _normalise(document):
        data = document.to_dict()
        data.setdefault("screening", None)
        return data

    def initialise(self, parse_jobs_ch_alert_metadata):
        for document in self.jobs.stream():
            data = self._normalise(document)
            title = data.get("title", "")
            if data.get("source") == "jobs.ch" and "Place of work" in title:
                parsed_title, parsed_company, parsed_location = parse_jobs_ch_alert_metadata(title)
                self.jobs.document(document.id).set({
                    "title": parsed_title,
                    "company": data.get("company") or parsed_company,
                    "location": data.get("location") or parsed_location,
                    "fallback_notified_at": None,
                }, merge=True)

    def save_discovered_jobs(self, jobs):
        operations = []
        for job in jobs:
            values = {
                "link": job["link"], "title": job["title"],
                "source": job.get("source", "jobs.ch"),
                "status": "discovered", "discovered_at": self._now(),
            }
            operations.append(lambda batch, job=job, values=values: batch.set(
                self.jobs.document(self._job_id(job["link"])), values, merge=True
            ))
        self._commit_operations(operations)

    def save_alert_jobs(self, jobs, normalise_job):
        batch = self.client.batch()
        for raw_job in jobs:
            job = normalise_job(raw_job)
            ref = self.jobs.document(self._job_id(job["link"]))
            existing = ref.get()
            if existing.exists:
                current = existing.to_dict()
                values = {
                    "title": job["title"] or current.get("title", ""),
                    "source": job.get("source", "jobs.ch"),
                    "company": job.get("company") or current.get("company"),
                    "location": job.get("location") or current.get("location"),
                    "posted_at": job.get("posted_at") or current.get("posted_at"),
                    "description": current.get("description") or job.get("description", ""),
                }
                if not current.get("archive_uri"):
                    values["status"] = "discovered"
            else:
                values = {
                    "link": job["link"], "title": job["title"],
                    "source": job.get("source", "jobs.ch"),
                    "company": job.get("company"), "location": job.get("location"),
                    "posted_at": job.get("posted_at"),
                    "description": job.get("description", ""),
                    "archive_uri": None, "status": "discovered",
                    "screening": None, "evaluation": None,
                    "fallback_notified_at": None, "discovered_at": self._now(),
                    "evaluated_at": None,
                }
            batch.set(ref, values, merge=True)
        batch.commit()

    def email_was_processed(self, mailbox, uid):
        return self.processed_emails.document(self._email_id(mailbox, uid)).get().exists

    def mark_email_processed(self, mailbox, uid):
        self.processed_emails.document(self._email_id(mailbox, uid)).set({
            "mailbox": mailbox, "uid": uid, "processed_at": self._now(),
        }, merge=True)

    def migrate_rows(self, jobs, processed_emails):
        operations = []
        for job in jobs:
            values = dict(job)
            values.pop("rowid", None)
            operations.append(lambda batch, job=job, values=values: batch.set(
                self.jobs.document(self._job_id(job["link"])), values, merge=True
            ))
        for item in processed_emails:
            operations.append(lambda batch, item=item: batch.set(
                self.processed_emails.document(self._email_id(item["mailbox"], item["uid"])),
                item, merge=True,
            ))
        self._commit_operations(operations)

    def jobs_by_status(self, *statuses):
        wanted = set(statuses)
        rows = [self._normalise(document) for document in self.jobs.stream()]
        return sorted(
            [row for row in rows if row.get("status") in wanted],
            key=lambda row: row.get("discovered_at") or "",
        )

    def fallback_jobs(self):
        rows = [self._normalise(document) for document in self.jobs.stream()]
        return sorted(
            [row for row in rows if row.get("status") != "emailed" and not row.get("fallback_notified_at")],
            key=lambda row: row.get("discovered_at") or "",
        )

    def update_jobs(self, jobs, values):
        batch = self.client.batch()
        for job in jobs:
            batch.set(self.jobs.document(self._job_id(job["link"])), values, merge=True)
        batch.commit()

    def mark_fallback_notified(self, jobs):
        self.update_jobs(jobs, {"fallback_notified_at": self._now()})

    def mark_details_failed(self, job):
        self.update_jobs([job], {"status": "details_failed"})

    def mark_emailed(self, jobs):
        self.update_jobs(jobs, {"status": "emailed"})

    def save_job_description(self, job, description, archive_uri):
        self.update_jobs([job], {"description": description, "archive_uri": archive_uri, "status": "ready"})

    def save_evaluations(self, jobs, batch_eval):
        batch = self.client.batch()
        for item in batch_eval.evaluations:
            index = item.job_index - 1
            if 0 <= index < len(jobs):
                batch.set(self.jobs.document(self._job_id(jobs[index]["link"])), {
                    "status": "evaluated", "evaluation": item.model_dump_json(),
                    "evaluated_at": self._now(),
                }, merge=True)
        batch.commit()

    def save_screening(self, jobs, batch_screening):
        batch = self.client.batch()
        for item in batch_screening.evaluations:
            index = item.job_index - 1
            if 0 <= index < len(jobs):
                batch.set(self.jobs.document(self._job_id(jobs[index]["link"])), {
                    "status": "screened" if item.is_potential_match else "rejected",
                    "screening": item.model_dump_json(),
                }, merge=True)
        batch.commit()

    def evaluated_jobs(self):
        return [
            row for row in (self._normalise(document) for document in self.jobs.stream())
            if row.get("status") == "evaluated"
        ]
