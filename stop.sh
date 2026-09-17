#!/usr/bin/env bash
# Stop the job-scraper dashboard stack (API + dev server) and clean up any
# leftover apply_helper.py / Playwright browser processes.
#
# Usage:
#   ./stop.sh                     # stop everything
#   ./stop.sh --keep-log          # same, but leave api.log/dashboard.log alone
set -e

cd "$(dirname "$0")"

stopped=0

# 1. FastAPI backend (uvicorn)
for pid in $(pgrep -f "uvicorn api.main:app" || true); do
    echo "[stop] stopping API (pid $pid)"
    kill "$pid" 2>/dev/null || true
    stopped=1
done

# 2. Vite dev server
for pid in $(pgrep -f "node .*vite" || true); do
    echo "[stop] stopping dashboard dev server (pid $pid)"
    kill "$pid" 2>/dev/null || true
    stopped=1
done

# 3. apply_helper.py + the Playwright browser it opens
for pid in $(pgrep -f "apply_helper.py" || true); do
    echo "[stop] stopping apply_helper (pid $pid)"
    kill "$pid" 2>/dev/null || true
    stopped=1
done
for pid in $(pgrep -f "playwright_chromiumdev_profile" || true); do
    echo "[stop] stopping Playwright browser (pid $pid)"
    kill -9 "$pid" 2>/dev/null || true
    stopped=1
done

# 4. systemd user units started by run_and_open.sh (if any)
for unit in dashboard-dev jobscrape runopen; do
    if systemctl --user is-active --quiet "$unit.service" 2>/dev/null; then
        echo "[stop] stopping systemd unit $unit.service"
        systemctl --user stop "$unit.service" 2>/dev/null || true
        stopped=1
    fi
done

if [ "$stopped" = "0" ]; then
    echo "[stop] nothing was running -- dashboard stack is already stopped."
else
    echo "[stop] done. Restart with ./run_and_open.sh"
fi