"""Full-coverage harvesting despite Algolia's pagination cap.

Algolia refuses to page past `paginationLimitedTo` (default 1000) results for a
single query. To pull an entire index we recursively partition the query space
until every slice has < cap hits, then page through each slice.

Two partitioning dimensions, applied in order:
  1. Facet drill-down — split by a high-cardinality categorical facet
     (e.g. category, purpose, make, city) from a per-vertical priority list.
  2. Numeric bisection — when facets are exhausted (or unhelpful), bisect a
     numeric attribute's value range (price, fallback a created-at timestamp)
     using numericFilters.

Hits are de-duplicated by objectID across slices, so overlap is harmless.
"""

from __future__ import annotations

import time
from typing import Callable

from .algolia import AlgoliaClient

# Algolia hard limits.
MAX_HITS_PER_PAGE = 1000
DEFAULT_CAP = 1000


def harvest(
    client: AlgoliaClient,
    index: str,
    *,
    base_params: dict | None = None,
    facet_priority: tuple[str, ...] = (),
    numeric_attr: str | None = "price",
    cap: int = DEFAULT_CAP,
    page_size: int = MAX_HITS_PER_PAGE,
    max_records: int | None = None,
    sleep: float = 0.0,
    log: Callable[[str], None] = print,
) -> list[dict]:
    """Return all hits for `index` under `base_params`, dedup'd by objectID."""
    base_params = dict(base_params or {})
    page_size = min(page_size, MAX_HITS_PER_PAGE)
    collected: dict[object, dict] = {}
    stats = {"queries": 0, "slices": 0}

    def _hit_id(h: dict):
        return h.get("objectID") or h.get("id") or h.get("externalID") or id(h)

    def _filters(flist: list[str]) -> str:
        return " AND ".join(flist)

    def _params(flist: list[str], numeric: list[str] | None = None) -> dict:
        p = dict(base_params)
        if flist:
            p["filters"] = _filters(flist)
        if numeric:
            p["numericFilters"] = numeric
        return p

    def _count(p: dict) -> int:
        stats["queries"] += 1
        return client.count(index, p)

    def _page_through(p: dict) -> None:
        stats["slices"] += 1
        # paginationLimitedTo means at most `cap` records are reachable here;
        # we only enter this for slices already known to be <= cap.
        max_pages = max(1, cap // page_size)
        page = 0
        while page < max_pages:
            q = dict(p)
            q["hitsPerPage"] = page_size
            q["page"] = page
            stats["queries"] += 1
            res = client.query(index, q)
            hits = res.get("hits") or []
            for h in hits:
                collected[_hit_id(h)] = h
            nb_pages = int(res.get("nbPages", 1))
            page += 1
            if page >= nb_pages:
                break
            if max_records and len(collected) >= max_records:
                break
            if sleep:
                time.sleep(sleep)

    def _bisect(flist: list[str], attr: str, lo: float, hi: float) -> None:
        if max_records and len(collected) >= max_records:
            return
        rng = [f"{attr}>={lo}", f"{attr}<{hi}"]
        p = _params(flist, rng)
        n = _count(p)
        if n == 0:
            return
        if n <= cap:
            _page_through(p)
            return
        if hi - lo <= 1:
            log(f"  WARN numeric bucket [{lo},{hi}) still {n}>{cap}; paging first {cap}")
            _page_through(p)
            return
        mid = (lo + hi) / 2
        if hi - lo > 2:  # keep integer boundaries for prices
            mid = float(int(mid))
        if mid <= lo or mid >= hi:
            mid = (lo + hi) / 2
        _bisect(flist, attr, lo, mid)
        _bisect(flist, attr, mid, hi)

    def _recurse(flist: list[str], facet_idx: int) -> None:
        if max_records and len(collected) >= max_records:
            return
        p = _params(flist)
        n = _count(p)
        if n == 0:
            return
        if n <= cap:
            _page_through(p)
            return
        # Try the next facet dimension.
        if facet_idx < len(facet_priority):
            attr = facet_priority[facet_idx]
            try:
                fv = client.facet_values(index, attr, p)
            except Exception:
                fv = {}
            # Useful only if it actually subdivides the slice.
            if fv and not (len(fv) == 1 and next(iter(fv.values())) >= n):
                for val in fv:
                    _recurse(flist + [f'{attr}:"{val}"'], facet_idx + 1)
                return
            # Facet didn't help — move to the next facet with the same filters.
            _recurse(flist, facet_idx + 1)
            return
        # Facets exhausted — bisect a numeric attribute.
        if numeric_attr:
            stat = client.numeric_stats(index, numeric_attr, p)
            if stat:
                lo, hi = stat
                _bisect(flist, numeric_attr, lo, hi + 1)  # +1 -> half-open includes max
                return
        log(f"  WARN cannot partition slice nbHits={n} filters={_filters(flist)!r}; paging first {cap}")
        _page_through(p)

    _recurse([], 0)
    log(f"  harvested {len(collected)} unique hits ({stats['queries']} queries, {stats['slices']} slices)")
    return list(collected.values())
