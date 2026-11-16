"""Download the full CMS Payroll Based Journal daily nurse staffing dataset to one CSV.

Usage:
    pip install requests
    python ingest_pbj.py                      # latest quarter -> pbj_daily_nurse_staffing.csv
    python ingest_pbj.py --out data/raw/pbj_2026q2.csv
    python ingest_pbj.py --dataset-id <uuid>  # a specific quarter's dataset id

What it does:
  - Pages through the API (default 5,000 rows per request).
  - Waits between requests so it does not hammer the server.
  - Retries failed requests with exponential backoff, and obeys the server's
    Retry-After header when it is rate limited (HTTP 429).
  - Writes to <out>.part and renames it only when the download is complete,
    so a half-finished file is never mistaken for a finished one.
  - If interrupted, rerun the same command and it resumes where it stopped.
  - Checks the final row count against the API's own total.
"""

import argparse
import csv
import os
import random
import sys
import time

import requests

BASE = "https://data.cms.gov/data-api/v1/dataset/{id}/data"
LATEST_ID = "7e0d53ba-8f02-4c66-98a5-14a1c997c50d"  # always points at the newest quarter

RETRY_STATUS = {429, 500, 502, 503, 504}


def get_json(session, url, params, max_retries, timeout):
    """GET a URL and return parsed JSON, retrying on network errors and 429/5xx."""
    for attempt in range(1, max_retries + 1):
        wait = min(120, 2 ** attempt) + random.uniform(0, 1)  # 2s, 4s, 8s ... capped at 2 min
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code in RETRY_STATUS:
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    wait = max(wait, int(retry_after))
                reason = f"HTTP {resp.status_code}"
            else:
                resp.raise_for_status()  # other 4xx errors are our fault: fail immediately
                return resp.json()
        except (requests.ConnectionError, requests.Timeout, ValueError) as exc:
            reason = f"{type(exc).__name__}: {exc}"  # ValueError = body was not valid JSON
        if attempt == max_retries:
            raise RuntimeError(f"Gave up after {max_retries} attempts ({reason}) at {params}")
        print(f"  attempt {attempt} failed ({reason}); retrying in {wait:.0f}s", flush=True)
        time.sleep(wait)


def rows_already_saved(path):
    """Count data rows in a partial file (header excluded) so a rerun can resume."""
    if not os.path.exists(path):
        return 0
    with open(path, newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", default="pbj_daily_nurse_staffing.csv")
    p.add_argument("--dataset-id", default=LATEST_ID)
    p.add_argument("--page-size", type=int, default=5000)
    p.add_argument("--delay", type=float, default=0.5, help="seconds to wait between requests")
    p.add_argument("--max-retries", type=int, default=8)
    p.add_argument("--timeout", type=int, default=120)
    args = p.parse_args()

    url = BASE.format(id=args.dataset_id)
    part = args.out + ".part"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = "pbj-portfolio-ingest/1.0"

    stats = get_json(session, url + "/stats", {}, args.max_retries, args.timeout)
    total = int(stats["total_rows"])
    print(f"Dataset has {total:,} rows")

    offset = rows_already_saved(part)
    if offset:
        print(f"Resuming from row {offset:,}")

    fieldnames = None
    if offset:
        with open(part, newline="", encoding="utf-8") as f:
            fieldnames = next(csv.reader(f))

    started = time.time()
    with open(part, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames) if fieldnames else None
        while offset < total:
            rows = get_json(session, url, {"size": args.page_size, "offset": offset},
                            args.max_retries, args.timeout)
            if not rows:
                break
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
            writer.writerows(rows)
            f.flush()
            offset += len(rows)
            print(f"  {offset:,} / {total:,} rows ({offset / total:.0%})", flush=True)
            time.sleep(args.delay)

    if offset != total:
        sys.exit(f"Row count mismatch: saved {offset:,}, expected {total:,}. "
                 f"Partial file kept at {part}; rerun to resume.")

    os.replace(part, args.out)
    print(f"Done: {offset:,} rows saved to {args.out} in {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
