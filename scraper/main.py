"""Daily dubizzle snapshot via headful-browser rendering.

dubizzle is behind Imperva and renders listings into the DOM (no clean API), so
we drive a real, human-paced browser, extract cards from each results page
(extract.py), map them to the target schema (schema.py), and write gzipped CSV.

On a residential IP no proxy is needed. On GitHub Actions, pass --proxy (uses
DUBIZZLE_PROXY_SUBSCRIPTION_URL) and run under xvfb so the browser is headful.
Crawl politely and slowly; the daily run accumulates coverage over time.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from .browser import human_browser, sleep
from .crawl import crawl_url
from .verticals import VERTICALS, columns_for, mapper_for

DATA_DIR = Path("data")


def write_csv_gz(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def run(verticals, max_pages, use_proxy, headless, slow, max_seeds=None):
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "verticals": {}}
    with human_browser(use_proxy=use_proxy, headless=headless, slow=slow) as page:
        for vertical in verticals:
            cfg = VERTICALS[vertical]
            columns = columns_for(vertical)
            mapper = mapper_for(vertical)
            vsummary = {"total": 0, "files": {}}
            seeds = cfg["seeds"][:max_seeds] if max_seeds else cfg["seeds"]
            for label, url in seeds:
                print(f"[{vertical}/{label}] {url}")
                cards = crawl_url(page, url, max_pages=max_pages, log=print)
                for c in cards:
                    c["category"] = label
                rows = [mapper(c) for c in cards]
                if rows:
                    out = DATA_DIR / vertical / f"{label}.csv.gz"
                    write_csv_gz(out, columns, rows)
                    vsummary["files"][f"{label}.csv.gz"] = len(rows)
                    vsummary["total"] += len(rows)
                sleep(3.0 * slow, 7.0 * slow)  # polite gap between categories
            summary["verticals"][vertical] = vsummary
            print(f"[{vertical}] total {vsummary['total']}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily dubizzle snapshot (rendered).")
    ap.add_argument("--vertical", action="append", help="limit to vertical(s)")
    ap.add_argument("--max-pages", type=int, default=3, help="pages per category")
    ap.add_argument("--max-seeds", type=int, default=None, help="limit categories per vertical")
    ap.add_argument("--proxy", action="store_true", help="route through DUBIZZLE_PROXY_SUBSCRIPTION_URL")
    ap.add_argument("--headless", action="store_true", help="headless (only works on residential IPs; Imperva blocks headless from datacenters)")
    ap.add_argument("--slow", type=float, default=1.0, help="scale human pauses (>1 = slower)")
    args = ap.parse_args()

    verticals = args.vertical or [v for v, c in VERTICALS.items() if c.get("enabled", True)]
    summary = run(verticals, args.max_pages, args.proxy, args.headless, args.slow, args.max_seeds)
    total = sum(v["total"] for v in summary["verticals"].values())
    print(f"\nDONE: {total} listings across {len(summary['verticals'])} verticals.")


if __name__ == "__main__":
    main()
