"""Stats + latest-run endpoints (top-level paths like /stats, /runs/latest)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from api import db

router = APIRouter()


@router.get("/stats")
def stats():
    now = datetime.now(timezone.utc)
    week_start = (
        datetime.combine((now - timedelta(days=now.weekday())).date(), datetime.min.time())
        .replace(tzinfo=timezone.utc)
    )

    with db.connect() as conn, conn.cursor() as cur:
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

    return {
        "by_status": by_status,
        "by_source": by_source,
        "new_this_week": new_this_week,
        "applied_series": applied_series,
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