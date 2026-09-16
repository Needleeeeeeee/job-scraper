"""Job listing / updating endpoints."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException

from api import db
from api.models import Job, JobStatusUpdate

router = APIRouter()


@router.get("", response_model=list[Job])
def list_jobs(
    status: str | None = None,
    source: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
):
    sql = "SELECT * FROM jobs WHERE 1=1"
    params: list = []

    if status:
        sql += " AND status = %s"
        params.append(status)
    if source:
        sql += " AND source = %s"
        params.append(source)
    if date_from:
        sql += " AND date_posted >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND date_posted <= %s"
        params.append(date_to)
    if search:
        sql += " AND (title ILIKE %s OR company ILIKE %s)"
        like = f"%{search}%"
        params.extend([like, like])

    sql += " ORDER BY date_posted DESC NULLS LAST, scraped_at DESC"

    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


@router.patch("/{job_id}", response_model=Job)
def update_status(job_id: int, body: JobStatusUpdate):
    with db.connect() as conn, conn.cursor() as cur:
        if body.status == "APPLIED":
            cur.execute(
                """
                UPDATE jobs SET status = %s, applied_at = %s
                WHERE id = %s RETURNING *
                """,
                (body.status, datetime.now(timezone.utc), job_id),
            )
        else:
            cur.execute(
                "UPDATE jobs SET status = %s WHERE id = %s RETURNING *",
                (body.status, job_id),
            )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))