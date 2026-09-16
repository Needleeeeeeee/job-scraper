"""Desktop-notification daemon for the job scraper.

Runs as a systemd *user* service (job-notifier.service). Polls
`paths.runs_log` (one summary line appended by main.py after every finished
run) and pops a desktop notification for each new line via notify-send,
which Omarchy's shell renders. Keeps a byte offset in .notify_state.json so
it only notifies about lines it hasn't seen, and never replays history on
startup.
"""
import json
import os
import shutil
import subprocess
import time

import yaml

POLL_INTERVAL_SECONDS = float(os.environ.get("NOTIFIER_POLL_SECONDS", "30"))
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".notify_state.json")

NOTIFY_BIN = shutil.which("notify-send") or "/usr/bin/notify-send"
if not os.path.exists(NOTIFY_BIN):
    NOTIFY_BIN = None


def load_config(config_path="config.yaml"):
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"inode": None, "size": 0}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def poll_once(log_path: str, state: dict):
    """Read any new `[run] ...` lines since the last poll. Returns the
    updated state plus the list of notification bodies."""
    try:
        st = os.stat(log_path)
    except FileNotFoundError:
        return state, []
    inode, size = st.st_ino, st.st_size

    # File was rotated or truncated -> start over from the top; otherwise
    # pick up only the bytes we haven't seen yet.
    start = 0 if state.get("inode") != inode or size < state.get("size", 0) else state.get("size", 0)

    messages = []
    if size > start:
        with open(log_path, "r", errors="replace") as f:
            f.seek(start)
            for line in f:
                line = line.strip()
                if line.startswith("[run] "):
                    messages.append(line[len("[run] "):])

    state.update({"inode": inode, "size": size})
    return state, messages


def notify(body: str):
    if not NOTIFY_BIN:
        print(f"[notifier] notify-send unavailable; skipping: {body}")
        return
    try:
        r = subprocess.run(
            [NOTIFY_BIN, "-a", "Job Scraper", "-u", "normal", "Job scrape complete", body],
            capture_output=True, text=True, timeout=15,
        )
        print(f"[notifier] showed: {body} (notify-send exit {r.returncode})")
    except Exception as e:
        print(f"[notifier] notify-send failed: {e}")


def main():
    cfg = load_config()
    log_path = cfg.get("paths", {}).get("runs_log", "runs.log")
    state = load_state()
    print(f"[notifier] watching {log_path} every {POLL_INTERVAL_SECONDS:.0f}s "
          f"(offset {state})")
    while True:
        try:
            state, messages = poll_once(log_path, state)
            for m in messages:
                notify(m)
            save_state(state)
        except Exception as e:
            print(f"[notifier] error: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()