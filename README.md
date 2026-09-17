# Job Search Scraper + Dashboard

Scrape pipeline + local web dashboard: scrapes Indeed, LinkedIn, and JobStreet
for junior/entry-level roles in Metro Manila, applies keyword +
years-of-experience filters, dedupes, and stores new leads in **Postgres**.
A **FastAPI** backend + **React/Tailwind** dashboard let you review and apply
to postings from a browser tab.

- New leads land in `jobs` (Postgres) with `status: NEW`; re-runs never
  duplicate rows.
- The dashboard lists postings, filters by status/source/date/text, and has an
  **Apply** button per row that opens the posting as a new tab in your
  existing browser.
- `applications.xlsx` support is kept behind `--legacy-xlsx` until you've
  confirmed the Postgres path on a few real runs.

## 1. Architecture

```
venv/bin/python main.py          scrape -> Postgres (jobs, scrape_runs)
job-dashboard-api.service         systemd user unit: FastAPI on :8000 (GET /jobs, PATCH, POST /jobs/{id}/apply, /stats, /runs/latest)
job-dashboard-web.service         systemd user unit: Vite + React + Tailwind dev server on :5173
dashboard/                        Vite + React + Tailwind dev server on :5173
run_and_open.sh                   scrape, ensure both servers, open the dashboard
stop.sh                           stop the API/dashboard + any leftover browser processes
apply_helper.py                   opens a job URL in a real browser and prefills form fields
notifier.py                       tails runs.log -> desktop notification (unchanged)
```

The API and dashboard run as **systemd user units**
(`job-dashboard-api.service`, `job-dashboard-web.service`), so they start at
login, survive tab reloads, and auto-restart if they crash. `git` this repo
does not contain them; the unit files live in `~/.config/systemd/user/`.

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

Or run the pieces by hand if you'd rather not use systemd:

```bash
venv/bin/python main.py                # scrape into Postgres (add --legacy-xlsx to mirror to xlsx)
systemctl --user start job-dashboard-api job-dashboard-web   # or uvicorn / npm run dev directly
```

`run_and_open.sh` ensures the API/dashboard servers are up (it starts the
systemd units if they're stopped, falling back to plain `nohup` processes if
systemd is unavailable), then opens `http://localhost:5173` in your default
browser. Manual CLI usage of the scraper still works (`venv/bin/python
main.py`); running it repeatedly is safe because duplicates are skipped.

To shut everything down (including any stray `apply_helper.py` / Playwright
browser left over from manual CLI use):

```bash
./stop.sh          # -> systemctl --user stop job-dashboard-api job-dashboard-web
```

Both units are `Restart=always` services, so `kill`ing the processes by hand
won't stick — use `stop.sh`, which stops the units themselves.

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
  `REJECTED` directly. Moving to `APPLIED` stamps `applied_at`; moving away
  from it clears `applied_at` so the chart stays accurate.
- **Apply** button opens the job URL in a new tab of your existing browser
  (`window.open`) and persists the row as `REVIEWED` (so the change survives
  a tab reload). Flip it to `APPLIED` manually after you've finished the
  application (apply_helper never files anything for you — some ATS
  platforms detect automation).
- **Search** filters live as you type. A plain query matches **title or
  company**; prefix it with `title:` to restrict the match to job titles
  only (e.g. `title:python`). Matching text is highlighted in the table.

`apply_helper.py` is unchanged in purpose but is no longer triggered by the
dashboard (Apply now just opens a new tab). It's still there for manual CLI
use and debugging when you want field prefill:

```bash
python apply_helper.py "https://ph.indeed.com/viewjob?jk=..." "my_resume.docx"
```

The resume path is optional; without it, text fields get prefilled but no
file upload is attempted.

## API

- `GET /jobs` — query params: `status`, `source`, `date_from`, `date_to`,
  `search` (title/company substring).
- `PATCH /jobs/{id}` — `{"status": "..."}`; sets `applied_at` when
  `APPLIED`, clears it when moving to any other status.
- `POST /jobs/{id}/apply` — resolves the job's URL (the dashboard opens it
  in a new tab; no browser automation).
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