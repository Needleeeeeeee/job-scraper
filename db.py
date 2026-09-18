"""
Postgres access helpers for the job scraper (psycopg2, plain SQL -- no ORM).

Connects over the local unix socket with the current OS user (peer auth),
matching the native-Postgres local setup. Override with the DATABASE_URL
env var if you run against a remote/explicit-credentials database.

Usage:
    import db
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(...)

    db.upsert_job({...})          # insert or ignore duplicates
"""
import os

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///job_scraper")


def connect():
    return psycopg2.connect(DATABASE_URL)


def find_existing(row: dict, conn=None):
    """Return the tracker DB row matching a scraped job, or None.

    Mirrors the old xlsx dedupe logic: normalized `url` first (exact match),
    falling back to title+company+location when the job has no URL.
    """
    conn = conn or connect()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        url = (row.get("url") or "").lower().rstrip("/")
        if url:
            cur.execute("SELECT * FROM jobs WHERE url = %s", (url,))
            r = cur.fetchone()
            if r:
                return dict(r)
        cur.execute(
            """
            SELECT * FROM jobs
            WHERE url = ''
              AND lower(title) = lower(%s)
              AND lower(coalesce(company, '')) = lower(%s)
              AND lower(coalesce(location, '')) = lower(%s)
            LIMIT 1
            """,
            (row.get("title", ""), row.get("company", ""), row.get("location", "")),
        )
        r = cur.fetchone()
        return dict(r) if r else None


def upsert_job(row: dict, conn=None) -> bool:
    """Insert a job, skipping PostgreSQL UNIQUE violations on `url`.

    Returns True when the row was actually inserted (new job), False when it
    was already present. This mirrors the old xlsx dedupe path -- URL first
    (the UNIQUE constraint catches exact matches) with a title+company
    fallback in the `find_existing` helper the caller should use too.
    """
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            url = (row.get("url") or "").lower().rstrip("/")
            cur.execute(
                """
                INSERT INTO jobs (source, title, company, url, location, date_posted, status)
                VALUES (%(source)s, %(title)s, %(company)s, %(url)s, %(location)s,
                        %(date_posted)s, %(status)s)
                """,
                {**row, "url": url},
            )
            conn.commit()
        return True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return False
    finally:
        if own:
            conn.close()


def record_run(started_at, finished_at, new_jobs_count, summary, conn=None) -> int:
    """Log a finished scrape into `scrape_runs` and return its id."""
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scrape_runs (started_at, finished_at, new_jobs_count, summary)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (started_at, finished_at, new_jobs_count, summary),
            )
            conn.commit()
            return cur.fetchone()[0]
    finally:
        if own:
            conn.close()


TRACKING_DDL = """
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TABLE IF NOT EXISTS job_status_history (
  id SERIAL PRIMARY KEY,
  job_id INT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  old_status TEXT,
  new_status TEXT NOT NULL,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_status_history_job_id_idx ON job_status_history(job_id);
CREATE INDEX IF NOT EXISTS job_status_history_changed_at_idx ON job_status_history(changed_at);
"""


def ensure_tracking_schema(conn=None):
    """Idempotently add negative-status tracking columns + history table.

    Safe to call on every startup: uses IF NOT EXISTS guards. Also
    backfills status_updated_at for pre-existing rows from
    COALESCE(applied_at, scraped_at) so the outcome graph has data
    even before any new dashboard decisions are made.
    """
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(TRACKING_DDL)
            cur.execute(
                """
                UPDATE jobs
                SET status_updated_at = COALESCE(applied_at, scraped_at)
                WHERE status_updated_at IS NULL
                """
            )
            conn.commit()
    finally:
        if own:
            conn.close()


def record_status_change(job_id: int, old_status, new_status: str, conn=None):
    """Append one row to job_status_history (caller owns the jobs UPDATE)."""
    own = conn is None
    if own:
        conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job_status_history (job_id, old_status, new_status)
                VALUES (%s, %s, %s)
                """,
                (job_id, old_status, new_status),
            )
            conn.commit()
    finally:
        if own:
            conn.close()