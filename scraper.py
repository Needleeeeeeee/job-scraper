"""
Scrapes job postings across configured sites/terms using python-jobspy,
applies keyword + experience filters, and returns a deduplicated DataFrame.

JobStreet is not supported by jobspy, so it is handled separately by
jobstreet.py (headless Chromium); this module merges its results in.
"""
import re

import yaml
import pandas as pd
from jobspy import scrape_jobs

import jobstreet
from locations import is_metro_manila


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


# Matches explicit years-of-experience requirements like:
#   "3-5 years experience", "2+ years of experience", "at least 3 years
#   experience", "minimum 5 years of relevant experience".
# We take the worst case (upper end of any range) and require the word
# "experience" to follow within a few words, so things like "25 years in
# business" don't nuke junior roles.
_MAX_EXP_PAT = re.compile(
    r"(\d{1,2})\b(?:\s*[-–to]+\s*(\d{1,2}))?\s*\+?\s*years?\b"
    r"(?:\s+\w+){0,4}\s+experience\b",
    re.IGNORECASE,
)

# Catch the flipped phrasing: "experience of 3 years", "experience with 2+ years"
_EXP_FIRST_PAT = re.compile(
    r"experience\s+(?:of|with|for|in)?\s*(\d{1,2})\b\s*\+?\s*years?\b",
    re.IGNORECASE,
)

# Catch "3 or more years of experience" / "3 plus years experience"
_EXP_OR_MORE_PAT = re.compile(
    r"(\d{1,2})\s+(?:or\s+more|plus)\s+years?\b(?:\s+\w+){0,4}\s+experience\b",
    re.IGNORECASE,
)

_NO_EXP_PAT = re.compile(
    r"\b(?:no\s+experience|fresh\s+graduate|entry[- ]level|0\s*years?\s*experience)\b",
    re.IGNORECASE,
)


def max_experience_years(text) -> float | None:
    """Highest explicit year requirement stated in the text, or None when no
    years-of-experience requirement is mentioned. Postings that say "no
    experience" / "fresh graduate" come back as 0."""
    if not isinstance(text, str) or not text.strip():
        return None
    low = re.sub(r"\s+", " ", text.lower())
    if _NO_EXP_PAT.search(low):
        return 0.0
    values = []
    for m in _MAX_EXP_PAT.finditer(low):
        values.extend(int(v) for v in m.groups() if v)
    for m in _EXP_FIRST_PAT.finditer(low):
        values.append(int(m.group(1)))
    for m in _EXP_OR_MORE_PAT.finditer(low):
        values.append(int(m.group(1)))
    return float(max(values)) if values else None


def normalize_url(url) -> str:
    if not isinstance(url, str):
        return ""
    return url.strip().lower().rstrip("/")


def scrape(cfg: dict) -> pd.DataFrame:
    s = cfg["search"]
    all_frames = []

    # jobspy only knows its own providers; JobStreet is scraped by jobstreet.py.
    sites = s.get("site_names", ["indeed", "linkedin"])
    jobspy_sites = [x for x in sites if x != "jobstreet"]
    use_jobstreet = "jobstreet" in sites
    terms = s["search_terms"]

    for term in terms:
        if not jobspy_sites:
            break
        print(f"[scraper] searching: '{term}' in {s['location']}")

        kwargs = dict(
            site_name=jobspy_sites,
            search_term=term,
            location=s["location"],
            results_wanted=s.get("results_wanted", 50),
            country_indeed=s.get("country_indeed", "Philippines"),  # required by Indeed/Glassdoor
            linkedin_fetch_description=s.get("linkedin_fetch_description", True),
        )

        # jobspy's Indeed integration rejects combining is_remote with
        # hours_old in one call (400 error) -- only pass is_remote through
        # when it's actually True (a remote-only search). For onsite/hybrid
        # searches (is_remote: false), we skip it entirely and rely on
        # hours_old + the post-scrape filters instead.
        if s.get("is_remote", False):
            kwargs["is_remote"] = True
        else:
            kwargs["hours_old"] = s.get("hours_old", 72)

        try:
            df = scrape_jobs(**kwargs)
        except Exception as e:
            print(f"[scraper] WARNING: search for '{term}' failed: {e}")
            continue
        if df is not None and not df.empty:
            df["matched_search_term"] = term
            all_frames.append(df)

    if use_jobstreet:
        try:
            js_df = jobstreet.scrape_jobstreet(
                terms,
                s["location"],
                max_results=s.get("results_wanted", 50),
                hours_old=s.get("hours_old"),
            )
        except Exception as e:
            print(f"[scraper] WARNING: jobstreet scrape failed: {e}")
            js_df = None
        if js_df is not None and not js_df.empty:
            all_frames.append(js_df)

    if not all_frames:
        return pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True)

    # Dedup within this run via normalized URL (falls back to title+company).
    if "job_url" in combined.columns:
        combined = combined[combined["job_url"].notna() & combined["job_url"].ne("")]
        combined["_urlkey"] = combined["job_url"].map(normalize_url)
        usable = combined[combined["_urlkey"].ne("")]
        if not usable.empty:
            usable = usable.drop_duplicates(subset=["_urlkey"])
            combined = pd.concat(
                [usable.drop(columns="_urlkey"), combined[combined["_urlkey"].eq("")]],
                ignore_index=True,
            )
    else:
        combined = combined.drop_duplicates(subset=["title", "company", "location"])

    combined = apply_keyword_filters(combined, s)
    return combined.reset_index(drop=True)


def apply_keyword_filters(df: pd.DataFrame, s: dict) -> pd.DataFrame:
    def title_ok(title: str) -> bool:
        if not isinstance(title, str):
            return False
        low = title.lower()
        if any(k.lower() in low for k in s.get("exclude_title_keywords", [])):
            return False
        levels = s.get("experience_level_keywords", [])
        if levels and not any(k.lower() in low for k in levels):
            return False
        return True

    def company_ok(company: str) -> bool:
        if not isinstance(company, str):
            return True
        low = company.lower()
        return not any(k.lower() in low for k in s.get("exclude_company_keywords", []))

    def experience_ok(description) -> bool:
        cap = s.get("max_experience_years")
        if not cap or not isinstance(description, str) or not description.strip():
            return True
        req = max_experience_years(description)
        return req is None or req <= cap

    mask = df["title"].apply(title_ok) & df["company"].apply(company_ok)
    if "location" in df.columns:
        mask = mask & df["location"].apply(is_metro_manila)
    if "description" in df.columns:
        mask = mask & df["description"].apply(experience_ok)
    return df[mask]


if __name__ == "__main__":
    cfg = load_config()
    jobs = scrape(cfg)
    print(f"[scraper] found {len(jobs)} jobs after filtering")
    if not jobs.empty:
        jobs.to_csv("raw_jobs.csv", index=False)
        print("[scraper] wrote raw_jobs.csv")