import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

const API = 'http://127.0.0.1:8000'

const STATUSES = ['NEW', 'REVIEWED', 'APPLIED', 'SKIP', 'REJECTED']
const SOURCES = ['indeed', 'linkedin', 'jobstreet']

const STATUS_STYLES = {
  NEW: 'bg-blue-100 text-blue-700 ring-blue-200 dark:bg-blue-900 dark:text-blue-300 dark:ring-blue-800',
  REVIEWED: 'bg-amber-100 text-amber-700 ring-amber-200 dark:bg-amber-900 dark:text-amber-300 dark:ring-amber-800',
  APPLIED: 'bg-emerald-100 text-emerald-700 ring-emerald-200 dark:bg-emerald-900 dark:text-emerald-300 dark:ring-emerald-800',
  SKIP: 'bg-slate-200 text-slate-600 ring-slate-300 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600',
  REJECTED: 'bg-rose-100 text-rose-700 ring-rose-200 dark:bg-rose-900 dark:text-rose-300 dark:ring-rose-800',
}

const SOURCE_STYLES = {
  indeed: 'bg-sky-100 text-sky-700 dark:bg-sky-900 dark:text-sky-300',
  linkedin: 'bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300',
  jobstreet: 'bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-900 dark:text-fuchsia-300',
}

function fmtDate(v) {
  if (!v) return '—'
  return String(v).slice(0, 10)
}

function timeAgo(iso) {
  if (!iso) return 'never'
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function Highlight({ text, query }) {
  const q = (query || '').trim().toLowerCase()
  const s = String(text || '')
  if (!q || !s) return s
  const i = s.toLowerCase().indexOf(q)
  if (i === -1) return s
  return (
    <>
      {s.slice(0, i)}
      <mark className="rounded bg-amber-200 px-0.5 text-inherit dark:bg-amber-700 dark:text-amber-100">
        {s.slice(i, i + q.length)}
      </mark>
      {s.slice(i + q.length)}
    </>
  )
}

function useDarkMode() {
  const [dark, setDark] = useState(() => {
    const stored = localStorage.getItem('theme')
    if (stored) return stored === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  useEffect(() => {
    const root = document.documentElement
    if (dark) {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  return [dark, setDark]
}

export default function App() {
  const [dark, setDark] = useDarkMode()
  const [jobs, setJobs] = useState([])
  const [stats, setStats] = useState(null)
  const [lastRun, setLastRun] = useState(null)
  const [loading, setLoading] = useState(true)

  const [status, setStatus] = useState('')
  const [source, setSource] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [search, setSearch] = useState('')
  const [hidden, setHidden] = useState([])
  const [pendingApply, setPendingApply] = useState(null)
  const [scraping, setScraping] = useState(false)
  const [scrapeNote, setScrapeNote] = useState('')

  const toggleHidden = useCallback((s) => {
    setHidden((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]))
  }, [])

  const fetchAll = useCallback(async () => {
    try {
      const [jobsRes, statsRes, runRes] = await Promise.all([
        fetch(API + '/jobs'),
        fetch(API + '/stats'),
        fetch(API + '/runs/latest'),
      ])
      const [j, st, r] = await Promise.all([
        jobsRes.json(),
        statsRes.json(),
        runRes.json(),
      ])
      setJobs(j)
      setStats(st)
      setLastRun(r)
    } catch (e) {
      console.error('dashboard fetch failed:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const t = setInterval(fetchAll, 60000)
    return () => clearInterval(t)
  }, [fetchAll])

  const parsedSearch = useMemo(() => {
    const raw = (search || '').trim()
    const titleOnly = /^title:/i.test(raw)
    return { titleOnly, q: raw.replace(/^title:/i, '').trim().toLowerCase() }
  }, [search])

  const filtered = useMemo(() => {
    const { titleOnly, q } = parsedSearch
    return jobs.filter((job) => {
      if (status && job.status !== status) return false
      // Negative filter-out tags: hidden statuses apply only when no
      // explicit status is selected (the dropdown takes precedence).
      if (!status && hidden.includes(job.status)) return false
      if (source && job.source !== source) return false
      if (dateFrom && String(job.date_posted || '').slice(0, 10) < dateFrom) return false
      if (dateTo && String(job.date_posted || '').slice(0, 10) > dateTo) return false
      if (q) {
        const inTitle = String(job.title || '').toLowerCase().includes(q)
        const inCompany = String(job.company || '').toLowerCase().includes(q)
        if (titleOnly ? !inTitle : !inTitle && !inCompany) return false
      }
      return true
    })
  }, [jobs, status, hidden, source, dateFrom, dateTo, parsedSearch])

  const hiddenCounts = useMemo(() => {
    const counts = {}
    for (const job of jobs) counts[job.status] = (counts[job.status] || 0) + 1
    return counts
  }, [jobs])

  const updateJobs = useCallback(
    (id, patch) => {
      setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, ...patch } : j)))
    },
    []
  )

  const changeStatus = useCallback(
    async (job, nextStatus) => {
      updateJobs(job.id, { status: nextStatus })
      try {
        await fetch(`${API}/jobs/${job.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: nextStatus }),
        })
        fetchAll()
      } catch (e) {
        console.error('status update failed:', e)
        fetchAll()
      }
    },
    [updateJobs, fetchAll]
  )

  const handleApply = useCallback(
    async (job) => {
      updateJobs(job.id, { status: 'REVIEWED' })
      setPendingApply(job.id)
      try {
        window.open(job.url, '_blank')
      } catch (e) {
        console.error('apply trigger failed:', e)
      }
      try {
        await fetch(`${API}/jobs/${job.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'REVIEWED' }),
        })
      } catch (e) {
        console.error('apply status persist failed:', e)
      }
      setPendingApply(null)
    },
    [updateJobs]
  )

  const handleScrape = useCallback(async () => {
    if (scraping) return
    setScraping(true)
    setScrapeNote('Starting scrape…')
    try {
      const startRes = await fetch(`${API}/scrape`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (startRes.status === 409) {
        setScrapeNote('A scrape is already running — waiting for it to finish…')
      } else if (!startRes.ok) {
        throw new Error(`scrape start failed (${startRes.status})`)
      } else {
        setScrapeNote('Scraping new jobs… you can keep reviewing while it runs.')
      }
      // Poll until the background scrape finishes, then refresh.
      for (;;) {
        await new Promise((r) => setTimeout(r, 3000))
        const sRes = await fetch(`${API}/scrape/status`)
        const s = await sRes.json()
        if (s.state === 'running' || s.state === 'idle') {
          continue
        }
        if (s.state === 'done') {
          setScrapeNote(
            s.added != null ? `Scrape finished: +${s.added} new (${s.scraped ?? 0} checked)` : 'Scrape finished.'
          )
        } else {
          setScrapeNote(s.error ? `Scrape failed: ${s.error}` : 'Scrape failed.')
        }
        break
      }
    } catch (e) {
      console.error('scrape trigger failed:', e)
      setScrapeNote('Could not start scrape — is the API running?')
    }
    await fetchAll()
    setScraping(false)
  }, [scraping, fetchAll])

  const barData = useMemo(() => {
    if (stats?.outcome_series?.length) return stats.outcome_series
    // Back-compat with older /stats that only sent applied_series.
    if (stats?.applied_series?.length)
      return stats.applied_series.map((r) => ({
        date: String(r.week || '').slice(0, 10),
        applied: r.count || 0,
        rejected: 0,
        skipped: 0,
      }))
    return []
  }, [stats])

  const decidedThisWeek = useMemo(() => {
    if (!stats) return 0
    if (
      stats.applied_this_week !== undefined ||
      stats.rejected_this_week !== undefined ||
      stats.skipped_this_week !== undefined
    )
      return (
        (stats.applied_this_week ?? 0) +
        (stats.rejected_this_week ?? 0) +
        (stats.skipped_this_week ?? 0)
      )
    // Fallback: sum the latest chart bucket.
    const last = barData[barData.length - 1]
    return last ? (last.applied || 0) + (last.rejected || 0) + (last.skipped || 0) : 0
  }, [stats, barData])

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 dark:bg-slate-950 dark:text-slate-200">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white px-6 py-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Job Scraper Dashboard</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Junior/entry-level roles · Metro Manila
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-medium ring-1 ${
                lastRun
                  ? 'bg-slate-100 text-slate-600 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700'
                  : 'bg-slate-100 text-slate-400 ring-slate-200 dark:bg-slate-800 dark:text-slate-500 dark:ring-slate-700'
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  lastRun ? 'bg-emerald-500' : 'bg-slate-400'
                }`}
              />
              Last scraped: {lastRun ? timeAgo(lastRun.finished_at) : '—'}
            </span>
            {lastRun?.new_jobs_count >= 0 && (
              <span className="text-slate-500 dark:text-slate-400">
                ({lastRun.new_jobs_count} new last run)
              </span>
            )}
            <button
              onClick={handleScrape}
              disabled={scraping}
              title="Scrape new jobs now (same as running main.py)"
              className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-blue-500 dark:hover:bg-blue-600"
            >
              {scraping ? 'Scraping…' : 'Scrape new jobs'}
            </button>
            <button
              onClick={() => setDark((d) => !d)}
              className="rounded-lg border border-slate-300 bg-slate-100 p-2 hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700"
              title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {dark ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="4"/>
                  <path d="M12 2v2"/>
                  <path d="M12 20v2"/>
                  <path d="m4.93 4.93 1.41 1.41"/>
                  <path d="m17.66 17.66 1.41 1.41"/>
                  <path d="M2 12h2"/>
                  <path d="M20 12h2"/>
                  <path d="m6.34 17.66-1.41 1.41"/>
                  <path d="m19.07 4.93-1.41 1.41"/>
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
                </svg>
              )}
            </button>
          </div>
        </div>
        {scrapeNote && (
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400" role="status">
            {scrapeNote}
          </p>
        )}
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <StatCard
            label="Total tracked"
            value={jobs.length}
            accent="bg-slate-800 dark:bg-slate-200"
          />
          <StatCard
            label="NEW this week"
            value={stats?.new_this_week ?? 0}
            accent="bg-blue-600"
          />
          <StatCard
            label="Applied (all time)"
            value={stats?.by_status?.APPLIED ?? 0}
            accent="bg-emerald-600"
          />
          <StatCard
            label="Rejected (all time)"
            value={stats?.by_status?.REJECTED ?? 0}
            accent="bg-rose-600"
          />
          <StatCard
            label="Skipped (all time)"
            value={stats?.by_status?.SKIP ?? 0}
            accent="bg-amber-500"
          />
          <StatCard
            label={`Decided this week (${barData.length} day${barData.length === 1 ? '' : 's'})`}
            value={decidedThisWeek}
            accent="bg-violet-600"
          />
        </section>

        {barData.length > 0 && (
          <section className="mt-6 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-400">
              Outcomes per day — applied vs rejected vs skipped
            </h2>
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={barData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={dark ? '#334155' : '#e2e8f0'} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={(v) => String(v).slice(5, 10)}
                    tick={{ fontSize: 12, fill: dark ? '#94a3b8' : '#64748b' }}
                  />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: dark ? '#94a3b8' : '#64748b' }} />
                  <Tooltip
                    labelFormatter={(v) => String(v).slice(0, 10)}
                    contentStyle={{
                      backgroundColor: dark ? '#1e293b' : '#fff',
                      border: dark ? '1px solid #334155' : '1px solid #e2e8f0',
                      borderRadius: '0.5rem',
                      color: dark ? '#e2e8f0' : '#1e293b',
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="applied" name="Applied" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="rejected" name="Rejected" stroke="#f43f5e" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="skipped" name="Skipped" stroke="#f59e0b" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}

        <section className="mt-6 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {['SKIP', 'REJECTED'].map((s) => {
            const isHidden = hidden.includes(s)
            return (
              <button
                key={s}
                onClick={() => toggleHidden(s)}
                title={isHidden ? `Show ${s} postings` : `Hide ${s} postings`}
                className={`rounded-full px-3 py-1.5 text-xs font-medium ring-1 transition ${
                  isHidden
                    ? s === 'REJECTED'
                      ? 'bg-rose-600 text-white ring-rose-600 dark:bg-rose-500 dark:ring-rose-500'
                      : 'bg-amber-500 text-white ring-amber-500'
                    : 'bg-white text-slate-500 ring-slate-300 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:ring-slate-700 dark:hover:bg-slate-700'
                }`}
              >
                {isHidden ? '✕' : '◌'} {s} ({hiddenCounts[s] || 0})
              </button>
            )
          })}
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
          >
            <option value="">All sources</option>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-400">
            From
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
            />
          </label>
          <label className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-400">
            To
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
            />
          </label>
          <input
            type="search"
            placeholder="Search title or company… (title:foo = titles only)"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="min-w-52 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
          <span className="text-sm text-slate-500 dark:text-slate-400">
            {filtered.length} of {jobs.length}
          </span>
        </section>

        <section className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          {loading ? (
            <div className="p-8 text-center text-sm text-slate-500 dark:text-slate-400">
              Loading jobs…
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-8 text-center text-sm text-slate-500 dark:text-slate-400">
              No jobs match your filters.
            </div>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400">
                <tr>
                  <th className="px-4 py-3 font-medium">Title</th>
                  <th className="px-4 py-3 font-medium">Company</th>
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 font-medium">Posted</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {filtered.map((job) => (
                  <tr key={job.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <td className="px-4 py-3">
                      <a
                        href={job.url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-slate-800 hover:text-blue-600 hover:underline dark:text-slate-200 dark:hover:text-blue-400"
                      >
                        <Highlight text={job.title || 'Untitled'} query={parsedSearch.q} />
                      </a>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      <Highlight text={job.company || '—'} query={parsedSearch.q} />
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block rounded px-2 py-0.5 text-xs font-medium capitalize ${
                          SOURCE_STYLES[job.source] || 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                        }`}
                      >
                        {job.source || '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      {fmtDate(job.date_posted)}
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={job.status}
                        onChange={(e) => changeStatus(job, e.target.value)}
                        className={`rounded-full border-0 px-3 py-1 text-xs font-medium ring-1 text-center ${
                          STATUS_STYLES[job.status] || 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                        }`}
                        title="Update status"
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleApply(job)}
                        disabled={pendingApply === job.id}
                        className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-blue-500 dark:hover:bg-blue-600"
                      >
                        {pendingApply === job.id ? 'Opening…' : 'Apply'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  )
}

function StatCard({ label, value, accent }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${accent}`} />
        <p className="text-sm text-slate-500 dark:text-slate-400">{label}</p>
      </div>
      <p className="mt-1 text-3xl font-semibold text-slate-800 dark:text-slate-100">{value}</p>
    </div>
  )
}