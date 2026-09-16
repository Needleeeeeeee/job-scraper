"""POST /jobs/{id}/apply -- shell out to apply_helper.py in a real browser."""
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api import db

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[2]
APPLY_HELPER = REPO_ROOT / "apply_helper.py"
PYTHON = REPO_ROOT / "venv" / "bin" / "python"
if not PYTHON.exists():  # fall back to whatever python is on PATH
    PYTHON = Path(sys.executable)

RESUME_BANK = REPO_ROOT / "resume_bank.yaml"


def _pick_resume() -> str:
    """Best-effort: pick the first .docx in the resumes/ dir, else '' (helper
    will just skip file inputs)."""
    resumes_dir = REPO_ROOT / "resumes"
    if resumes_dir.is_dir():
        docs = sorted(resumes_dir.glob("*.docx"))
        if docs:
            return str(docs[0])
    return ""


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

    resume = _pick_resume()
    cmd = [str(PYTHON), str(APPLY_HELPER), url]
    if resume:
        cmd.append(resume)

    # Detached subprocess so we can return immediately; the browser window
    # opens on the user's desktop. apply_helper.py prompts for Enter at the
    # end, which we close its stdin so that prompt returns immediately after
    # the user closes the tab.
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"could not start apply_helper: {e}")

    return {"ok": True, "job_id": job_id, "url": url}