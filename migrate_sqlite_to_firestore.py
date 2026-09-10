import argparse
import sqlite3
from pathlib import Path

from src.services.job_store import FirestoreJobStore


def migrate(database_path, project_id, credentials_path, collection):
    store = FirestoreJobStore(project_id, credentials_path, collection)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        jobs = [dict(row) for row in connection.execute("SELECT * FROM jobs")]
        processed_emails = [
            dict(row) for row in connection.execute(
                "SELECT mailbox, uid, processed_at FROM processed_emails"
            )
        ]

    store.migrate_rows(jobs, processed_emails)
    print(f"Migrated {len(jobs)} job(s) and {len(processed_emails)} processed email record(s).")


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite state to Firestore.")
    parser.add_argument("--database", default="jobs.sqlite3")
    parser.add_argument("--project", required=True)
    parser.add_argument("--credentials", default="google-service-account.json")
    parser.add_argument("--collection", default="jobs")
    args = parser.parse_args()
    migrate(Path(args.database), args.project, args.credentials, args.collection)


if __name__ == "__main__":
    main()
