"""Stats + latest-run endpoints (top-level paths like /stats, /runs/latest)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from api import db

router = APIRouter()

OUTCOME_STATUSES = ("APPLIED", "REJECTED", "SKIP")


def _weekly_series(cur, status: str) -> list[dict]:
    """Weekly counts of dashboard decisions into `status`.

    Prefers the job_status_history audit trail (exact decision time);
    falls back to status_updated_at / applied_at on jobs when the
    history table has no rows yet (e.g. decisions made before this
    tracking was added).
    """
    cur.execute("SELECT count(*) FROM job_status_history WHERE new_status = %s", (status,))
    if (cur.fetchone() or [0])[0]:
        cur.execute(
            """
            SELECT date_trunc('week', changed_at) AS week, count(*) AS n
            FROM job_status_history
            WHERE new_status = %s
            GROUP BY week ORDER BY week
            """,
            (status,),
        )
        return [{"week": week.isoformat(), "count": n} for week, n in cur.fetchall()]
    ts_col = "applied_at" if status == "APPLIED" else "status_updated_at"
    cur.execute(
        f"""
        SELECT date_trunc('week', {ts_col}) AS week, count(*) AS n
        FROM jobs
        WHERE status = %s AND {ts_col} IS NOT NULL
        GROUP BY week ORDER BY week
        """,
        (status,),
    )
    return [{"week": week.isoformat(), "count": n} for week, n in cur.fetchall()]


@router.get("/stats")
def stats():
    now = datetime.now(timezone.utc)
    week_start = (
        datetime.combine((now - timedelta(days=now.weekday())).date(), datetime.min.time())
        .replace(tzinfo=timezone.utc)
    )

    with db.connect() as conn, conn.cursor() as cur:
        # Ensure tracking columns exist even if schema.sql wasn't re-applied.
        try:
            cur.execute(
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS "
                "status_updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS job_status_history (
                  id SERIAL PRIMARY KEY,
                  job_id INT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  old_status TEXT,
                  new_status TEXT NOT NULL,
                  changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.commit()
        except Exception:
            conn.rollback()

        cur.execute(
            "SELECT status, count(*) AS n FROM jobs GROUP BY status ORDER BY status"
        )
        by_status = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute(
            "SELECT source, count(*) AS n FROM jobs GROUP BY source ORDER BY source"
        )
        by_source = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute(
            "SELECT count(*) FROM jobs WHERE status = 'NEW' AND scraped_at >= %s",
            (week_start,),
        )
        new_this_week = cur.fetchone()[0]

        cur.execute(
            "SELECT count(*) FROM jobs WHERE status = 'APPLIED' AND status_updated_at >= %s",
            (week_start,),
        )
        applied_this_week = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM jobs WHERE status = 'REJECTED' AND status_updated_at >= %s",
            (week_start,),
        )
        rejected_this_week = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM jobs WHERE status = 'SKIP' AND status_updated_at >= %s",
            (week_start,),
        )
        skipped_this_week = cur.fetchone()[0]

        cur.execute(
            """
            SELECT date_trunc('week', applied_at) AS week, count(*) AS n
            FROM jobs
            WHERE applied_at IS NOT NULL
            GROUP BY week ORDER BY week
            """
        )
        applied_series = [
            {"week": week.isoformat(), "count": n} for week, n in cur.fetchall()
        ]

        rejected_series = _weekly_series(cur, "REJECTED")
        skipped_series = _weekly_series(cur, "SKIP")

        # Merged per-week outcome buckets for the stacked/grouped graph.
        by_week: dict[str, dict] = {}
        for week_row in applied_series:
            by_week.setdefault(week_row["week"], {"week": week_row["week"],
                                                  "applied": 0, "rejected": 0, "skipped": 0})
            by_week[week_row["week"]]["applied"] = week_row["count"]
        for week_row in rejected_series:
            by_week.setdefault(week_row["week"], {"week": week_row["week"],
                                                  "applied": 0, "rejected": 0, "skipped": 0})
            by_week[week_row["week"]]["rejected"] = week_row["count"]
        for week_row in skipped_series:
            by_week.setdefault(week_row["week"], {"week": week_row["week"],
                                                  "applied": 0, "rejected": 0, "skipped": 0})
            by_week[week_row["week"]]["skipped"] = week_row["count"]
        outcome_series = [by_week[k] for k in sorted(by_week)]

    return {
        "by_status": by_status,
        "by_source": by_source,
        "new_this_week": new_this_week,
        "applied_series": applied_series,
        "rejected_series": rejected_series,
        "skipped_series": skipped_series,
        "outcome_series": outcome_series,
        "applied_this_week": applied_this_week,
        "rejected_this_week": rejected_this_week,
        "skipped_this_week": skipped_this_week,
    }


@router.get("/runs/latest")
def latest_run():
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT 1")
        row = cur.fetchone()
    if not row:
        return None
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))