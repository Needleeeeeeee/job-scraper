"""
Scrape-only pipeline: scrape -> filter -> dedupe (within run + vs tracker) -> Postgres.

    python main.py            # store new leads in Postgres
    python main.py --legacy-xlsx   # ALSO mirror to applications.xlsx (old path)

Then open the dashboard (or applications.xlsx with --legacy-xlsx) and review
the NEW rows. Mark rows REVIEWED / APPLIED as you go; existing rows are never
re-added on later runs.
"""
import argparse
import math
from datetime import datetime, timezone

import yaml

from scraper import load_config, scrape
import tracker

import db


def _is_missing(value) -> bool:
    """True for NaN floats and pandas NaT dates."""
    if isinstance(value, float):
        return math.isnan(value)
    try:
        import pandas as pd
        if value is pd.NaT:
            return True
    except Exception:
        pass
    return False


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _source(row) -> str:
    """Map the scraper's site label onto the schema's source enum."""
    site = _clean(row.get("site", "")).lower()
    if not site:
        url = _clean(row.get("job_url", "")).lower()
        if "jobstreet" in url:
            return "jobstreet"
        if "indeed" in url:
            return "indeed"
        if "linkedin" in url:
            return "linkedin"
        return ""
    for needle in ("indeed", "linkedin", "jobstreet"):
        if needle in site:
            return needle
    return site


def _jrow(job) -> dict:
    dpost = job.get("date_posted")
    if dpost is None or _is_missing(dpost):
        dpost = None
    return {
        "source": _source(job),
        "title": _clean(job.get("title", "")),
        "company": _clean(job.get("company", "")),
        "url": _clean(job.get("job_url", "")).lower().rstrip("/"),
        "location": _clean(job.get("location", "")),
        "date_posted": dpost,
        "status": "NEW",
    }


def _xrow(job) -> dict:
    return {
        "status": "NEW",
        "title": _clean(job.get("title", "")),
        "company": _clean(job.get("company", "")),
        "location": _clean(job.get("location", "")),
        "date_posted": job.get("date_posted", ""),
        "job_url": _clean(job.get("job_url", "")),
        "search_term": _clean(job.get("matched_search_term", "")),
        "notes": "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-xlsx", action="store_true",
                    help="also mirror new rows into applications.xlsx")
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    cfg = load_config()
    try:
        db.ensure_tracking_schema()
    except Exception as e:
        print(f"[main] WARNING: tracking migration failed: {e}")
    jobs = scrape(cfg)
    print(f"[main] {len(jobs)} jobs after scraping + filters")
    if jobs.empty:
        print("[main] nothing found -- check config.yaml search terms/location.")
        return

    sheet_path = cfg["paths"]["tracker_sheet"]
    df = tracker.load_or_init(sheet_path) if args.legacy_xlsx else None

    added = 0
    for _, job in jobs.iterrows():
        row = _jrow(job)
        if db.find_existing(row) is not None:
            continue
        if db.upsert_job(row):
            added += 1
            if args.legacy_xlsx:
                df = tracker.upsert(df, _xrow(job))

    if args.legacy_xlsx:
        tracker.save(df, sheet_path)

    finished = datetime.now(timezone.utc)
    summary = (
        f"[run] {datetime.now().strftime('%a %b %d %H:%M')} · "
        f"{added} new · {len(jobs)} scraped"
    )
    print(summary)

    try:
        db.record_run(started, finished, added, summary)
    except Exception as e:
        print(f"[main] WARNING: could not log scrape run: {e}")

    run_log = cfg["paths"]["runs_log"]
    with open(run_log, "a") as f:
        f.write(summary + "\n")


if __name__ == "__main__":
    main()