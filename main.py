"""
Scrape-only pipeline: scrape -> filter -> dedupe (within run + vs tracker) -> update sheet.

    python main.py

Then open applications.xlsx and review the NEW rows. Mark rows REVIEWED /
APPLIED as you go; existing rows are never re-added on later runs.
"""
import math
from datetime import datetime

import yaml

from scraper import load_config, scrape
import tracker


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _job_key(row) -> str:
    """Stable identity for a job: normalized URL when available, else
    title+company+location. Used to skip jobs already in the tracker."""
    url = _clean(row.get("job_url", ""))
    if url:
        return "url:" + url.lower().rstrip("/")
    return "fallback:" + "|".join(
        _clean(row.get(k, "")).lower() for k in ("title", "company", "location")
    )


def main():
    cfg = load_config()
    jobs = scrape(cfg)
    print(f"[main] {len(jobs)} jobs after scraping + filters")
    if jobs.empty:
        print("[main] nothing found -- check config.yaml search terms/location.")
        return

    sheet_path = cfg["paths"]["tracker_sheet"]
    df = tracker.load_or_init(sheet_path)
    seen = set()
    if not df.empty:
        seen = {_job_key(row) for _, row in df.iterrows()}

    added = 0
    for _, job in jobs.iterrows():
        key = _job_key(job)
        if key in seen:
            continue
        seen.add(key)
        df = tracker.upsert(df, {
            "status": "NEW",
            "title": _clean(job.get("title", "")),
            "company": _clean(job.get("company", "")),
            "location": _clean(job.get("location", "")),
            "date_posted": job.get("date_posted", ""),
            "job_url": _clean(job.get("job_url", "")),
            "search_term": _clean(job.get("matched_search_term", "")),
            "notes": "",
        })
        added += 1

    tracker.save(df, sheet_path)
    summary = (
        f"[run] {datetime.now().strftime('%a %b %d %H:%M')} · "
        f"{added} new · {len(df)} tracked · {len(jobs)} scraped"
    )
    print(summary)
    run_log = cfg["paths"]["runs_log"]
    with open(run_log, "a") as f:
        f.write(summary + "\n")


if __name__ == "__main__":
    main()