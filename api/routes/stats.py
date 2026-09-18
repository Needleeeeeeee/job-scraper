"""Stats + latest-run endpoints (top-level paths like /stats, /runs/latest)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from api import db

router = APIRouter()

OUTCOME_STATUSES = ("APPLIED", "REJECTED", "SKIP", "MISMATCH", "EXP_GAP")
# Dashboard graph keys per outcome status.
_SERIES_KEYS = {"APPLIED": "applied", "REJECTED": "rejected", "SKIP": "skipped",
                "MISMATCH": "mismatch", "EXP_GAP": "expgap"}


def _daily_series(cur, status: str) -> list[dict]:
    """Daily counts of dashboard decisions into `status`.

    Merges two sources so pre-tracking decisions aren't lost:
    - `job_status_history` events (exact, for decisions made in the
      dashboard since tracking was added), plus
    - one synthetic event per decided job that has NO history rows yet
      (decisions predating the tracker), dated at `status_updated_at`.
    Jobs with history rows are excluded from the legacy branch, so
    nothing is double-counted.
    """
    cur.execute(
        """
        SELECT day, SUM(n) AS n FROM (
          SELECT date_trunc('day', changed_at)::date AS day, count(*) AS n
          FROM job_status_history
          WHERE new_status = %s
          GROUP BY 1
          UNION ALL
          SELECT date_trunc('day', status_updated_at)::date AS day, count(*) AS n
          FROM jobs
          WHERE status = %s
            AND id NOT IN (SELECT job_id FROM job_status_history)
          GROUP BY 1
        ) s GROUP BY day ORDER BY day
        """,
        (status, status),
    )
    return [{"date": day.isoformat(), "count": int(n)} for day, n in cur.fetchall()]


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
            "SELECT count(*) FROM jobs WHERE status = 'MISMATCH' AND status_updated_at >= %s",
            (week_start,),
        )
        mismatch_this_week = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM jobs WHERE status = 'EXP_GAP' AND status_updated_at >= %s",
            (week_start,),
        )
        expgap_this_week = cur.fetchone()[0]

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

        rejected_series = _daily_series(cur, "REJECTED")
        skipped_series = _daily_series(cur, "SKIP")
        applied_daily = _daily_series(cur, "APPLIED")
        mismatch_series = _daily_series(cur, "MISMATCH")
        expgap_series = _daily_series(cur, "EXP_GAP")

        # Merged per-day outcome buckets for the line graph.
        by_day: dict[str, dict] = {}

        def _blank(date: str) -> dict:
            return {"date": date, "applied": 0, "rejected": 0, "skipped": 0,
                    "mismatch": 0, "expgap": 0}

        for day_row, key in ((applied_daily, "applied"),
                             (rejected_series, "rejected"),
                             (skipped_series, "skipped"),
                             (mismatch_series, "mismatch"),
                             (expgap_series, "expgap")):
            for row in day_row:
                by_day.setdefault(row["date"], _blank(row["date"]))
                by_day[row["date"]][key] = row["count"]
        outcome_series = [by_day[k] for k in sorted(by_day)]

    return {
        "by_status": by_status,
        "by_source": by_source,
        "new_this_week": new_this_week,
        "applied_series": applied_series,
        "rejected_series": rejected_series,
        "skipped_series": skipped_series,
        "mismatch_series": mismatch_series,
        "expgap_series": expgap_series,
        "outcome_series": outcome_series,
        "applied_this_week": applied_this_week,
        "rejected_this_week": rejected_this_week,
        "skipped_this_week": skipped_this_week,
        "mismatch_this_week": mismatch_this_week,
        "expgap_this_week": expgap_this_week,
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