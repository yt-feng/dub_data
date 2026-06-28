"""Orchestrate a full daily snapshot of dubizzle via its Algolia backend.

Flow:
  1. (optional) pick a working proxy and bootstrap fresh Algolia keys.
  2. for each enabled vertical: harvest every listing with full coverage
     (partition.py), map hits to the target schema (schema.py), and write
     gzipped CSV files grouped by a per-vertical split key.
  3. write data/summary.json with counts, the run timestamp, and a key
     fingerprint (so key rotation is visible in git history).

Images are stored as original URLs only (images/0..9 + a JSON `images` column),
never downloaded — as requested.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import bootstrap_keys
from . import proxy as proxymod
from .algolia import AlgoliaClient
from .partition import harvest
from .verticals import VERTICALS, columns_for, mapper_for

DATA_DIR = Path("data")


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12] if value else ""


def _write_csv_gz(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def harvest_vertical(
    vertical: str,
    keys: dict,
    *,
    proxies: dict | None,
    limit: int | None,
    sleep: float,
) -> dict:
    cfg = VERTICALS[vertical]
    creds = keys[vertical]
    columns = columns_for(vertical)
    mapper = mapper_for(vertical)
    split_key = cfg["split_key"]
    numeric_attr = cfg.get("numeric_attr", "price")

    # Prefer the facets the live site itself uses (guaranteed facetable),
    # excluding the numeric attribute we bisect on; fall back to config.
    site_facets = [f for f in creds.get("facets", []) if f and f != numeric_attr]
    facet_priority = tuple(site_facets) or cfg["facet_priority"]

    client = AlgoliaClient(
        creds["app_id"], creds["api_key"], host=creds.get("host"), proxies=proxies
    )

    base_params = {
        "query": "",
        "attributesToRetrieve": ["*"],
        "attributesToHighlight": [],
        "getRankingInfo": False,
    }

    print(f"[{vertical}] index={creds['index']} facets={facet_priority}")
    hits = harvest(
        client,
        creds["index"],
        base_params=base_params,
        facet_priority=facet_priority,
        numeric_attr=numeric_attr,
        max_records=limit,
        sleep=sleep,
        log=lambda m: print(f"[{vertical}]{m}"),
    )

    grouped: dict[str, list[dict]] = defaultdict(list)
    for hit in hits:
        row = mapper(hit)
        grouped[split_key(row) or "all"].append(row)

    out_dir = DATA_DIR / vertical
    # Clear stale files for this vertical so deleted categories don't linger.
    if out_dir.exists():
        for old in out_dir.glob("*.csv.gz"):
            old.unlink()

    file_counts = {}
    for key, rows in sorted(grouped.items()):
        fname = f"{key}.csv.gz"
        _write_csv_gz(out_dir / fname, columns, rows)
        file_counts[fname] = len(rows)

    return {
        "total": len(hits),
        "files": file_counts,
        "index": creds["index"],
        "app_id": creds["app_id"],
        "key_fingerprint": _fingerprint(creds["api_key"]),
        "listing_url": creds.get("listing_url", ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily dubizzle snapshot via Algolia.")
    ap.add_argument("--vertical", action="append", help="limit to vertical(s)")
    ap.add_argument("--limit", type=int, default=None, help="max records per vertical (testing)")
    ap.add_argument("--no-bootstrap", action="store_true", help="reuse cached config/keys.json")
    ap.add_argument("--no-proxy", action="store_true", help="don't use a proxy for bootstrap")
    ap.add_argument("--proxy-harvest", action="store_true", help="route Algolia harvest through the proxy too")
    ap.add_argument("--sleep", type=float, default=0.0, help="delay between Algolia pages")
    args = ap.parse_args()

    selected = args.vertical or [v for v, c in VERTICALS.items() if c.get("enabled", True)]

    # Keys: bootstrap fresh (default) or reuse cache.
    if args.no_bootstrap:
        keys = bootstrap_keys.load_keys()
        if not keys:
            raise SystemExit("No cached config/keys.json; run without --no-bootstrap.")
    else:
        keys = bootstrap_keys.bootstrap(use_proxy=not args.no_proxy)
        if not keys:  # fall back to any cached keys
            keys = bootstrap_keys.load_keys()
        if not keys:
            raise SystemExit("Could not obtain Algolia keys (bootstrap failed, no cache).")

    # Optional proxy for harvesting (Algolia is usually reachable directly).
    harvest_proxies = None
    if args.proxy_harvest:
        picked = proxymod.pick_working_proxy()
        if picked:
            harvest_proxies = {"http": picked[0], "https": picked[0]}

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verticals": {},
    }
    for vertical in selected:
        if vertical not in keys:
            print(f"[{vertical}] no keys captured — skipping")
            continue
        summary["verticals"][vertical] = harvest_vertical(
            vertical, keys, proxies=harvest_proxies, limit=args.limit, sleep=args.sleep
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    total = sum(v["total"] for v in summary["verticals"].values())
    print(f"\nDONE: {total} listings across {len(summary['verticals'])} verticals.")


if __name__ == "__main__":
    main()
