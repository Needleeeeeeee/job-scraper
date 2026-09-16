#!/usr/bin/env bash
# Run the scraper, then make sure API + dashboard are up and open the
# dashboard in the default browser.
#
# Usage:
#   ./run_and_open.sh                # scrape + open dashboard
#   ./run_and_open.sh --legacy-xlsx  # also mirror to applications.xlsx
#
# Scheduled (timer) auto-open is intentionally NOT wired up anymore -- the
# user scrapped scheduled fires. Run this manually whenever you want fresh
# postings reviewed right away.
set -e

cd "$(dirname "$0")"

API_URL="http://127.0.0.1:8000"
DASH_URL="http://localhost:5173"
API_LOG="api.log"
DASH_LOG="dashboard.log"

echo "[run_and_open] scraping..."
if [ -x venv/bin/python ]; then
    venv/bin/python main.py "$@"
else
    python3 main.py "$@"
fi

# --- start the API if it isn't already serving ---
if ! curl -sf "$API_URL/health" >/dev/null 2>&1; then
    echo "[run_and_open] starting API (uvicorn) -> $API_URL"
    if [ -x venv/bin/uvicorn ]; then
        nohup venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 \
            >> "$API_LOG" 2>&1 &
    else
        nohup python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000 \
            >> "$API_LOG" 2>&1 &
    fi
fi

# --- start the dashboard dev server if it isn't already serving ---
if ! curl -sf "$DASH_URL" >/dev/null 2>&1; then
    echo "[run_and_open] starting dashboard (vite) -> $DASH_URL"
    if command -v npm >/dev/null 2>&1; then
        (cd dashboard && nohup npm run dev > "../$DASH_LOG" 2>&1 &)
    else
        echo "WARNING: npm not found; can't start the dashboard." >&2
    fi
fi

# --- wait briefly for the servers, then open the dashboard ---
for i in $(seq 1 30); do
    if curl -sf "$DASH_URL" >/dev/null 2>&1 && curl -sf "$API_URL/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo "[run_and_open] opening $DASH_URL"
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$DASH_URL" >/dev/null 2>&1 || true
else
    echo "xdg-open not found -- open $DASH_URL yourself."
fi

echo "[run_and_open] done."