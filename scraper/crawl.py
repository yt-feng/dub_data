"""Crawl one results URL across pages, human-like, extracting cards per page."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from .browser import pass_challenge, human_scroll, sleep
from .extract import EXTRACT_JS, normalize


def _with_page(url: str, page_no: int) -> str:
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query))
    q["page"] = str(page_no)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))


def crawl_url(
    page,
    url: str,
    *,
    max_pages: int = 3,
    log=print,
) -> list[dict]:
    """Return de-duplicated cards from up to `max_pages` of a results URL.

    Stops early when a page yields no new cards (end of results / soft-block).
    """
    slow = getattr(page, "_slow", 1.0)
    collected: dict[str, dict] = {}
    for page_no in range(1, max_pages + 1):
        target = _with_page(url, page_no)
        ok = pass_challenge(page, target)
        if not ok:
            log(f"    page {page_no}: challenge not cleared; stopping")
            break
        human_scroll(page, steps=16)
        try:
            cards = page.evaluate(EXTRACT_JS)
        except Exception as exc:
            log(f"    page {page_no}: extract error {exc}")
            break
        new = 0
        for c in cards:
            key = c.get("url") or ""
            if key and key not in collected:
                collected[key] = normalize(c)
                new += 1
        log(f"    page {page_no}: {len(cards)} cards, {new} new (total {len(collected)})")
        if new == 0:
            break
        sleep(2.0 * slow, 4.5 * slow)  # polite gap between pages
    return list(collected.values())
