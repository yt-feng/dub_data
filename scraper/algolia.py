"""Minimal Algolia search client.

dubizzle's listing pages query an Algolia index. We talk to the same
`/1/indexes/*/queries` endpoint the browser uses, with the public search key
captured by bootstrap_keys.py. The endpoint is reachable from any IP (it is a
SaaS, not behind dubizzle's Imperva), so harvesting works fine from GitHub
Actions runners.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode

import requests


def encode_params(params: dict) -> str:
    """URL-encode Algolia search params.

    Array/object values (facets, numericFilters, attributesToRetrieve, ...)
    must be JSON-encoded first; scalars pass through. The whole thing is then
    form-urlencoded into the `params` string of a multi-query request.
    """
    flat = {}
    for key, value in params.items():
        if isinstance(value, (list, dict, bool)):
            flat[key] = json.dumps(value)
        else:
            flat[key] = value
    return urlencode(flat)


class AlgoliaError(RuntimeError):
    pass


class AlgoliaClient:
    def __init__(
        self,
        app_id: str,
        api_key: str,
        host: str | None = None,
        proxies: dict[str, str] | None = None,
        timeout: int = 30,
        user_agent: str = "Mozilla/5.0",
    ):
        self.app_id = app_id
        self.api_key = api_key
        self.timeout = timeout
        self.proxies = proxies
        # Hosts to try in order. Algolia exposes -dsn (read) plus three
        # numbered fallbacks. We honour an explicitly captured host first.
        hosts: list[str] = []
        if host:
            hosts.append(host)
        hosts += [
            f"{app_id.lower()}-dsn.algolia.net",
            f"{app_id.lower()}-1.algolianet.com",
            f"{app_id.lower()}-2.algolianet.com",
            f"{app_id.lower()}-3.algolianet.com",
        ]
        # de-dup preserving order
        seen: set[str] = set()
        self.hosts = [h for h in hosts if not (h in seen or seen.add(h))]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Algolia-Application-Id": app_id,
                "X-Algolia-API-Key": api_key,
                "Content-Type": "application/json",
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )

    def _post(self, path: str, body: dict) -> dict:
        last_err: Exception | None = None
        for host in self.hosts:
            url = f"https://{host}{path}"
            for attempt in range(4):
                try:
                    resp = self.session.post(
                        url, json=body, timeout=self.timeout, proxies=self.proxies
                    )
                    if resp.status_code == 429 or resp.status_code >= 500:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    if resp.status_code == 403:
                        raise AlgoliaError(
                            f"403 from Algolia (key likely rotated): {resp.text[:200]}"
                        )
                    resp.raise_for_status()
                    return resp.json()
                except AlgoliaError:
                    raise
                except Exception as exc:  # network / parse — try next host/attempt
                    last_err = exc
                    time.sleep(1.0 * (attempt + 1))
            # move on to next host
        raise AlgoliaError(f"All Algolia hosts failed: {last_err}")

    def query(self, index: str, params: dict) -> dict:
        """Run a single query against `index`. `params` are Algolia search
        params (page, hitsPerPage, filters, numericFilters, facets, ...)."""
        body = {
            "requests": [
                {"indexName": index, "params": encode_params(params)}
            ]
        }
        out = self._post("/1/indexes/*/queries", body)
        results = out.get("results") or []
        if not results:
            raise AlgoliaError(f"Empty results for index {index}")
        return results[0]

    def count(self, index: str, params: dict) -> int:
        """nbHits for a query (cheap: hitsPerPage=0)."""
        p = dict(params)
        p["hitsPerPage"] = 0
        p["page"] = 0
        return int(self.query(index, p).get("nbHits", 0))

    def facet_values(
        self, index: str, facet: str, params: dict, max_values: int = 1000
    ) -> dict[str, int]:
        """Return {facet_value: count} for a facet under the given filters."""
        p = dict(params)
        p["hitsPerPage"] = 0
        p["page"] = 0
        p["facets"] = [facet]
        p["maxValuesPerFacet"] = max_values
        res = self.query(index, p)
        return (res.get("facets") or {}).get(facet, {})

    def numeric_stats(self, index: str, attr: str, params: dict) -> tuple[float, float] | None:
        """Return (min, max) of a numeric attribute under filters, via
        facets_stats. Requires `attr` to be configured as a numeric facet."""
        p = dict(params)
        p["hitsPerPage"] = 0
        p["page"] = 0
        p["facets"] = [attr]
        res = self.query(index, p)
        stats = (res.get("facets_stats") or {}).get(attr)
        if not stats:
            return None
        return float(stats.get("min")), float(stats.get("max"))
