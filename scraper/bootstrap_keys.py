"""Discover dubizzle's current Algolia credentials with a real browser.

dubizzle's HTML is behind Imperva, which blocks datacenter IPs. We therefore
drive a headless Chromium through a residential/proxy node (see proxy.py), open
one listing page per vertical, and capture the Algolia request the page fires:
  - host            ({appId}-dsn.algolia.net)
  - application id   (header or query: x-algolia-application-id)
  - api key          (header or query: x-algolia-api-key)
  - index name       (request body: requests[].indexName)
  - sample params    (request body: requests[].params) -> facets the site uses
  - a sample hit     (from the response) -> lets us tighten field mapping

Results are written to config/keys.json. Re-running refreshes everything, so a
rotated key is picked up automatically on the next scheduled run.

If no proxy is available you can seed keys manually instead — see
`seed_from_capture()` and the README's browser-console snippet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import proxy as proxymod
from .verticals import VERTICALS

KEYS_PATH = Path("config/keys.json")
NAV_TIMEOUT_MS = 45_000
SETTLE_MS = 6_000


def _parse_algolia(url: str, headers: dict, post_data: str | None) -> dict | None:
    """Pull appId/key/index/params from a captured Algolia request."""
    if "algolia" not in url:
        return None
    host = urlsplit(url).hostname or ""
    qs = parse_qs(urlsplit(url).query)
    hdr = {k.lower(): v for k, v in (headers or {}).items()}

    app_id = (
        hdr.get("x-algolia-application-id")
        or (qs.get("x-algolia-application-id") or [None])[0]
    )
    api_key = (
        hdr.get("x-algolia-api-key")
        or (qs.get("x-algolia-api-key") or [None])[0]
    )

    index = None
    params = None
    if post_data:
        try:
            body = json.loads(post_data)
            reqs = body.get("requests") or []
            if reqs:
                # prefer the request with the richest params (the main listing query)
                reqs.sort(key=lambda r: len(r.get("params", "")), reverse=True)
                index = reqs[0].get("indexName")
                params = reqs[0].get("params")
        except Exception:
            pass

    if not (app_id and api_key and index):
        return None
    return {
        "host": host,
        "app_id": app_id,
        "api_key": api_key,
        "index": index,
        "sample_params": params or "",
    }


def _facets_from_params(params: str) -> list[str]:
    if not params:
        return []
    qs = parse_qs(params)
    raw = qs.get("facets", [])
    facets: list[str] = []
    for item in raw:
        try:
            val = json.loads(item)
            if isinstance(val, list):
                facets.extend(val)
            elif isinstance(val, str):
                facets.append(val)
        except Exception:
            facets.append(item)
    return [f for f in facets if f and f != "*"]


def capture_with_browser(proxy_url: str | None) -> dict:
    """Open each vertical's listing page and capture its Algolia call."""
    from playwright.sync_api import sync_playwright

    results: dict[str, dict] = {}
    launch_kwargs = {"headless": True}
    if proxy_url:
        launch_kwargs["proxy"] = proxymod.playwright_proxy_arg(proxy_url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        for vertical, cfg in VERTICALS.items():
            if not cfg.get("enabled", True):
                continue
            captured: list[dict] = []
            sample_hit: dict | None = None
            page = ctx.new_page()

            def on_request(req):
                info = _parse_algolia(req.url, req.headers, req.post_data)
                if info:
                    captured.append(info)

            def on_response(resp):
                nonlocal sample_hit
                if sample_hit is None and "algolia" in resp.url:
                    try:
                        data = resp.json()
                        hits = (data.get("results") or [{}])[0].get("hits") or []
                        if hits:
                            sample_hit = hits[0]
                    except Exception:
                        pass

            page.on("request", on_request)
            page.on("response", on_response)

            for url in cfg["listing_urls"]:
                try:
                    page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                    page.wait_for_timeout(SETTLE_MS)
                except Exception as exc:
                    print(f"[{vertical}] {url} -> {exc}", file=sys.stderr)
                if captured:
                    print(f"[{vertical}] captured Algolia via {url}")
                    break

            if captured:
                best = max(captured, key=lambda c: len(c.get("sample_params", "")))
                best["facets"] = _facets_from_params(best.get("sample_params", ""))
                best["listing_url"] = url
                if sample_hit is not None:
                    best["sample_hit"] = sample_hit
                results[vertical] = best
            else:
                print(f"[{vertical}] FAILED to capture Algolia request", file=sys.stderr)

            page.close()
        browser.close()
    return results


def bootstrap(use_proxy: bool = True) -> dict:
    proxy_url = None
    if use_proxy:
        picked = proxymod.pick_working_proxy()
        if picked:
            proxy_url, ip = picked
            print(f"Using proxy egress IP {ip}")
        else:
            print("WARNING: no working proxy; trying direct (Imperva may block).", file=sys.stderr)

    results = capture_with_browser(proxy_url)
    if results:
        KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
        KEYS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"Wrote {KEYS_PATH} with verticals: {', '.join(results)}")
    return results


def load_keys() -> dict:
    if KEYS_PATH.exists():
        return json.loads(KEYS_PATH.read_text())
    return {}


if __name__ == "__main__":
    bootstrap(use_proxy="--no-proxy" not in sys.argv)
