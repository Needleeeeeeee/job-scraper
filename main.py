"""
Scrape-only pipeline: scrape -> filter -> dedupe (within run + vs tracker) -> Postgres.

    python main.py            # store new leads in Postgres
    python main.py --legacy-xlsx   # ALSO mirror to applications.xlsx (old path)

Then open the dashboard (or applications.xlsx with --legacy-xlsx) and review
the NEW rows. Mark rows REVIEWED / APPLIED as you go; existing rows are never
re-added on later runs.
"""
import argparse

from pipeline import run_scrape


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-xlsx", action="store_true",
                    help="also mirror new rows into applications.xlsx")
    args = ap.parse_args()

    result = run_scrape(legacy_xlsx=args.legacy_xlsx)
    print(result["summary"])


if __name__ == "__main__":
    main()