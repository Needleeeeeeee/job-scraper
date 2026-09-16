# Job Search Scraper + Tracker

Scrape-only pipeline: scrapes Indeed, LinkedIn, and JobStreet for
junior/entry-level roles in Metro Manila, applies keyword +
years-of-experience filters, dedupes against everything already seen, and
appends only the new leads to `applications.xlsx`. No LLM APIs, no keys,
nothing to budget.

## 1. Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # needed for JobStreet scraping + apply_helper.py
```

No `.env`, no API keys.

## 2. Set your search parameters

Edit `config.yaml` only:

- `search.search_terms` — one jobspy search runs per term (each pulls up to
  `results_wanted` per board). Keep them junior/entry-level friendly.
- `search.location` — default `"Metro Manila, Philippines"`; combined with
  `search.country_indeed: "Philippines"` this keeps results local.
- **Strict location gating (always on):** after scraping, every row is
  checked against a Metro Manila / National Capital Region whitelist
  (16 cities + Pateros + NCR markers; see `locations.py`). Any posting whose
  location is explicitly outside the NCR — Cebu, Davao, Iloilo, Bacolod,
  Cavite, Clark, Angeles, Baguio, etc. — is dropped no matter what the
  search itself returns. Postings with no location at all are kept.
- `search.results_wanted` — max per search term per job board (default 50).
- `search.hours_old` — how far back to look (default 72h).
- `search.max_experience_years` — a posting that *explicitly* requires more
  than this many years is dropped (parses phrases like "3-5 years
  experience"). Postings with no stated requirement are kept.
- `search.exclude_title_keywords` — prefix/seniority terms dropped by title.
- `search.exclude_company_keywords` — companies to drop by name.
- `search.site_names` — which boards to scrape (`indeed`, `linkedin`,
  `jobstreet`). JobStreet is not supported by jobspy, so it is scraped by
  `jobstreet.py` through a headless Chromium (the same Playwright browser
  installed above). It ignores the `", Philippines"` suffix on `location`.

## 3. Run it

```bash
venv/bin/python main.py
```

What happens:

1. Scrape each term on each site (`linkedin_fetch_description: true` is
   required, or LinkedIn descriptions come back empty and the
   years-experience filter can't run).
2. Deduplicate within the run by job URL.
3. Filter by title keywords and the years requirement.
4. Load `applications.xlsx`, compute the set of jobs already tracked
   (by normalized URL, falling back to title+company), and append only the
   NEW jobs with `status: NEW`.
5. Write the sheet back sorted newest-first.

Re-runs never duplicate a row: a job already in the sheet is skipped, so
running 3–5x a week just keeps the sheet topped up with new postings.

## 4. Schedule it (installed)

A systemd **user** timer runs `main.py` three times a week and catches up
on anything missed while the machine was off:

```bash
Mon/Wed/Fri 09:00  ->  ~/.config/systemd/user/job-auto-apply.timer
```

- See the next scheduled run: `systemctl --user list-timers job-auto-apply.timer`
- Force a run now: `systemctl --user start job-auto-apply.service`
- Read the last run's log: `journalctl --user -u job-auto-apply -n 50`
- Want 5 runs/week instead of 3? In the timer file change the `OnCalendar`
  line to `Mon-Fri 09:00`, then `systemctl --user daemon-reload`.
- Unscheduled runs don't duplicate rows anyway, so running manually in
  addition is safe.

Note: systemd user timers fire only while you're logged into your desktop
session; `Persistent=true` makes it catch up missed runs after login.

### Desktop notifications

A companion **user** daemon (`job-notifier.service`, auto-started at login)
pops a desktop notification every time a scrape run finishes:

- It tails `paths.runs_log` (one summary line per run, written by
  `main.py`) and calls `notify-send` — rendered by the Omarchy shell.
- Watch it live: `journalctl --user -u job-notifier -f`
- Stop/start it: `systemctl --user stop job-notifier.service` /
  `systemctl --user start job-notifier.service`
- Adjust how often it polls: `systemctl --user edit job-notifier.service`
  → add `Environment=NOTIFIER_POLL_SECONDS=60`.

## 5. Review and apply

Open `applications.xlsx`. New rows are `status: NEW`. To apply to a row:

```bash
python apply_helper.py "<job_url>"
```

This opens a real browser window and tries to auto-fill
name/email/phone/resume-upload fields, then leaves the tab open for you to
check and hit submit. Update the row's `status` (`REVIEWED` / `APPLIED` /
`SKIP` / `REJECTED`) so future runs' dedupe keys stay sane and the sheet
stays your source of truth.

## Troubleshooting: 400 errors from the scraper

Two jobspy quirks cause most 400s:

1. **`country_indeed` is required for Indeed/Glassdoor and defaults to
   `'USA'`.** If you're searching a non-US location and this isn't set in
   `config.yaml`'s `search.country_indeed`, Indeed will 400 (or silently
   search the wrong country). Must match jobspy's exact spelling.
2. **jobspy's Indeed integration rejects combining `is_remote` with
   `hours_old` in the same call.** `scraper.py` handles this: it only
   sends `is_remote` when it's `true`; for onsite/hybrid searches
   (`is_remote: false`) it omits the field and relies on `hours_old`
   instead.

Since `is_remote: false` isn't sent to the API as a filter, some remote-only
postings may slip through. Add `"remote"` to `search.exclude_title_keywords`
if you want those dropped by title.

If you still hit a 400 after both fixes, run
`venv/bin/python scraper.py` directly to see the raw error, and check
jobspy's GitHub issues for your exact site — its scrapers reverse-engineer
LinkedIn/Indeed's internal APIs, so they occasionally break when those
sites change something.

## Notes / limits

- The years filter is heuristic (text parsing). A posting that doesn't
  mention years is kept; one that says "20 years in business" near the
  word "experience" could get dropped. Review rows in the sheet as needed.
- `apply_helper.py` fills forms, it never clicks final submit — some ATS
  platforms (Workday especially) actively detect and block automation, so
  keep this manual step.
- Indoor-only scoring/tailoring (the old resume-tailoring pipeline) was
  archived under `.archive-tailoring/` — nothing imports it anymore.
- Greenhouse/Lever/company-board direct scraping isn't wired up yet
  (`config.yaml`'s `company_boards` section is a placeholder) — those
  boards expose stabler JSON endpoints than LinkedIn/Indeed scraping if you
  want that added.