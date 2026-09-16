CREATE TABLE IF NOT EXISTS jobs (
  id SERIAL PRIMARY KEY,
  source TEXT NOT NULL,           -- indeed | linkedin | jobstreet
  title TEXT NOT NULL,
  company TEXT NOT NULL,
  url TEXT UNIQUE NOT NULL,       -- dedupe key, mirrors current normalized-URL logic
  location TEXT,
  date_posted DATE,
  status TEXT NOT NULL DEFAULT 'NEW',  -- NEW/REVIEWED/APPLIED/SKIP/REJECTED
  scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  applied_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS scrape_runs (
  id SERIAL PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  new_jobs_count INT,
  summary TEXT
);