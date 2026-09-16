# Job Search Scraper + Dashboard

Scrape pipeline + local web dashboard: scrapes Indeed, LinkedIn, and JobStreet
for junior/entry-level roles in Metro Manila, applies keyword +
years-of-experience filters, dedupes, and stores new leads in **Postgres**.
A **FastAPI** backend + **React/Tailwind** dashboard let you review and apply
to postings from a browser tab.

- New leads land in `jobs` (Postgres) with `status: NEW`; re-runs never
  duplicate rows.
- The dashboard lists postings, filters by status/source/date/text, and has an
  **Apply** button per row that opens a real browser via `apply_helper.py`.
- `applications.xlsx` support is kept behind `--legacy-xlsx` until you've
  confirmed the Postgres path on a few real runs.

## 1. Architecture

```
venv/bin/python main.py          scrape -> Postgres (jobs, scrape_runs)
venv/bin/uvicorn api.main:app     FastAPI on :8000 (GET /jobs, PATCH, POST /jobs/{id}/apply, /stats, /runs/latest)
dashboard/                        Vite + React + Tailwind dev server on :5173
run_and_open.sh                   scrape, ensure both servers, open the dashboard
apply_helper.py                   opens a job URL in a real browser and prefills form fields
notifier.py                       tails runs.log -> desktop notification (unchanged)
```

## 2. Setup

```bash
# Postgres (native, no Docker)
sudo pacman -S postgresql              # Arch/Omarchy
sudo -u postgres initdb -D /var/lib/postgres/data
sudo systemctl enable --now postgresql
sudo -u postgres psql -c "CREATE ROLE <your_os_username> LOGIN SUPERUSER;"   # your OS user
createdb job_scraper
psql -d job_scraper -f schema.sql      # creates jobs + scrape_runs

# Python deps
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium            # JobStreet scraping + apply_helper.py

# Dashboard deps
cd dashboard && npm install && cd ..
```

`db.py` connects over the local socket as your OS user (peer auth); override
with the `DATABASE_URL` env var if you ever point it elsewhere.

## 3. Run it

```bash
./run_and_open.sh                      # scrape -> ensure API/dashboard -> open browser
./run_and_open.sh --legacy-xlsx        # also mirror new rows to applications.xlsx
```

Or run the pieces by hand:

```bash
venv/bin/python main.py                # scrape into Postgres (add --legacy-xlsx to mirror to xlsx)
venv/bin/uvicorn api.main:app --reload --port 8000        # API
cd dashboard && npm run dev                                 # dashboard on :5173
```

`run_and_open.sh` starts the API/dashboard dev servers automatically if they
aren't already running, then opens `http://localhost:5173` in your default
browser. Manual CLI usage of the scraper still works (`venv/bin/python
main.py`); running it repeatedly is safe because duplicates are skipped.

### Scheduled runs (removed)

The old `job-auto-apply.timer` (Mon/Wed/Fri 09:00) has been **disabled and
unarmed** per request — no scheduled fires. `run_and_open.sh` is the manual
entry point for turning freshly-scraped postings into a browser tab. The
timer/notifier unit files still exist under `~/.config/systemd/user/` if you
want to re-enable or repurpose them later.

The `job-notifier.service` desktop-notification daemon is unchanged and still
tails `runs.log`.

## 4. Review and apply

Open the dashboard and check the **NEW** rows:

- **Status** badge is a dropdown — set `REVIEWED` / `APPLIED` / `SKIP` /
  `REJECTED` directly (moving to `APPLIED` also stamps `applied_at`).
- **Apply** button calls `POST /jobs/{id}/apply`, which shells out to
  `apply_helper.py "<url>"`. Clicking Apply optimistically marks the row
  `REVIEWED`; it's your call to flip it to `APPLIED` after you confirm the
  form in the opened browser tab (apply_helper never clicks submit on
  purpose — some ATS platforms detect automation).

`apply_helper.py` hasn't changed in purpose — it's now triggered from the
dashboard's Apply button instead of the CLI, but manual CLI debugging still
works:

```bash
python apply_helper.py "https://ph.indeed.com/viewjob?jk=..." "my_resume.docx"
```

The resume path is optional; without it, text fields get prefilled but no
file upload is attempted.

## API

- `GET /jobs` — query params: `status`, `source`, `date_from`, `date_to`,
  `search` (title/company substring).
- `PATCH /jobs/{id}` — `{"status": "..."}`; sets `applied_at` when
  `APPLIED`.
- `POST /jobs/{id}/apply` — launches `apply_helper.py` on the job's URL.
- `GET /stats` — counts by status/source, new-this-week, applied-over-time.
- `GET /runs/latest` — most recent `scrape_runs` row.
- Interactive docs at `http://127.0.0.1:8000/docs`.

This is a local single-user tool: no auth, no cloud deployment. CORS is
limited to localhost origins.

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
  word "experience" could get dropped. Review rows in the dashboard as
  needed.
- `apply_helper.py` fills forms, it never clicks final submit — some ATS
  platforms (Workday especially) actively detect and block automation, so
  keep this manual step.
- `applications.xlsx` is still written when you pass `--legacy-xlsx`; the
  Postgres `jobs` table is the new source of truth and the dashboard reads
  only Postgres.
- Indoor-only scoring/tailoring (the old resume-tailoring pipeline) was
  archived under `.archive-tailoring/` — nothing imports it anymore.
- Greenhouse/Lever/company-board direct scraping isn't wired up yet
  (`config.yaml`'s `company_boards` section is a placeholder) — those
  boards expose stabler JSON endpoints than LinkedIn/Indeed scraping if you
  want that added.