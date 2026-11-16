"""Download a CMS Provider Data Catalog dataset (default: Nursing Home Provider
Information) to a single CSV in the data/ folder.

Usage:
    pip install requests
    python ingest_provider_info.py                     # -> data/nh_provider_info.csv
    python ingest_provider_info.py --dataset-id <other-id> --out data/other.csv

What it does:
  - Pages through the API (default 500 rows per request).
  - Waits between requests so it does not hammer the server.
  - Retries failed requests with exponential backoff, and obeys the server's
    Retry-After header when it is rate limited (HTTP 429).
  - Writes to <out>.part and renames it only when the download is complete.
  - Checks the saved row count against the total the API reports.

This file is a monthly snapshot of currently active nursing homes. The
`processing_date` column tells you which snapshot you have.
"""

import argparse
import csv
import os
import random
import sys
import time

import requests

BASE = "https://data.cms.gov/provider-data/api/1/datastore/query/{id}/0"
PROVIDER_INFO_ID = "4pq5-n9py"

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


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", default=os.path.join("data", "nh_provider_info.csv"))
    p.add_argument("--dataset-id", default=PROVIDER_INFO_ID)
    p.add_argument("--page-size", type=int, default=500)
    p.add_argument("--delay", type=float, default=0.5, help="seconds to wait between requests")
    p.add_argument("--max-retries", type=int, default=8)
    p.add_argument("--timeout", type=int, default=120)
    args = p.parse_args()

    url = BASE.format(id=args.dataset_id)
    part = args.out + ".part"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    session = requests.Session()

    started = time.time()
    offset, total, writer = 0, None, None
    with open(part, "w", newline="", encoding="utf-8") as f:
        while total is None or offset < total:
            page = get_json(session, url, {"limit": args.page_size, "offset": offset},
                            args.max_retries, args.timeout)
            rows = page.get("results", [])
            if total is None:
                total = int(page["count"])
                print(f"Dataset has {total:,} rows")
            if not rows:
                break
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
            writer.writerows(rows)
            offset += len(rows)
            print(f"  {offset:,} / {total:,} rows ({offset / total:.0%})", flush=True)
            time.sleep(args.delay)

    if offset != total:
        sys.exit(f"Row count mismatch: saved {offset:,}, expected {total:,}. "
                 f"Partial file left at {part}; rerun to start again.")

    os.replace(part, args.out)
    print(f"Done: {offset:,} rows saved to {args.out} in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
