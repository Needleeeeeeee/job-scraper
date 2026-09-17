"""POST /jobs/{id}/apply -- resolve a job URL for the dashboard's Apply button.

Apply no longer spawns apply_helper.py's separate browser window: the
dashboard opens the job URL directly in a new tab of your existing browser
(`window.open`). apply_helper.py is still available for manual CLI use
(`python apply_helper.py <url>`).
"""
from fastapi import APIRouter, HTTPException

from api import db

router = APIRouter()


@router.post("/{job_id}/apply")
def trigger_apply(job_id: int):
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT url FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="job not found")

    url = row[0] or ""
    if not url:
        raise HTTPException(status_code=400, detail="job has no URL to apply to")

    return {"ok": True, "job_id": job_id, "url": url}