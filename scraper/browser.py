"""Headful Chromium with human-like behaviour to get past Imperva.

dubizzle is protected by Imperva, which fingerprints headless/automated
browsers and bursty behaviour. We therefore:
  - launch *headful* Chromium (under xvfb on CI) with automation flags off,
  - move/scroll gradually with randomised pauses,
  - wait for the JS challenge to clear before doing anything.

On a residential IP (your laptop) no proxy is needed. On GitHub's datacenter
IPs a residential proxy (DUBIZZLE_PROXY_SUBSCRIPTION_URL) is required.
"""

from __future__ import annotations

import contextlib
import random
import time

from . import proxy as proxymod
from .forwarder import LocalForwarder

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def sleep(lo: float, hi: float | None = None) -> None:
    time.sleep(random.uniform(lo, hi if hi is not None else lo * 1.6))


@contextlib.contextmanager
def human_browser(use_proxy: bool = False, headless: bool = False, slow: float = 1.0):
    """Yield a Playwright page ready to drive. `slow` scales all human pauses."""
    from playwright.sync_api import sync_playwright

    forwarder_cm = contextlib.nullcontext()
    proxy_arg = None
    if use_proxy:
        picked = proxymod.pick_working_proxy()
        if picked:
            upstream, ip = picked
            # Chromium can't use the upstream (https / socks5-auth) directly, so
            # tunnel through a local plain-http forwarder.
            forwarder_cm = LocalForwarder(upstream)
            print(f"[browser] proxy egress IP {ip}")
        else:
            print("[browser] WARNING no working proxy; going direct")

    with forwarder_cm as fwd, sync_playwright() as pw:
        if fwd is not None:
            proxy_arg = {"server": fwd.endpoint}
        launch_kwargs = dict(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-sandbox",
            ],
        )
        if proxy_arg:
            launch_kwargs["proxy"] = proxy_arg
        browser = pw.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(
            user_agent=UA,
            locale="en-US",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        # Hide the webdriver flag a bit more.
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()
        page._slow = slow  # type: ignore[attr-defined]
        try:
            yield page
        finally:
            with contextlib.suppress(Exception):
                browser.close()


def pass_challenge(page, url: str, *, max_wait: float = 60.0) -> bool:
    """Navigate and wait for the Imperva interstitial to clear."""
    slow = getattr(page, "_slow", 1.0)
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
    except Exception as exc:
        print(f"[browser] goto error {exc}")
    deadline = time.time() + max_wait
    while time.time() < deadline:
        sleep(1.5 * slow, 2.5 * slow)
        try:
            body = page.content()
        except Exception:
            continue  # navigating (challenge solving)
        if len(body) > 25000 and "Pardon Our Interruption" not in body:
            sleep(1.0 * slow, 2.0 * slow)
            return True
    return False


def human_scroll(page, *, steps: int = 14, settle: bool = True) -> None:
    """Scroll down gradually with pauses, occasionally easing back up, so lazy
    content loads without looking like a bot."""
    slow = getattr(page, "_slow", 1.0)
    for i in range(steps):
        dy = random.randint(280, 620)
        with contextlib.suppress(Exception):
            page.mouse.move(random.randint(200, 1200), random.randint(150, 800))
            page.mouse.wheel(0, dy)
        sleep(0.5 * slow, 1.4 * slow)
        if i and i % 5 == 0:  # occasional small scroll-up, like a human re-reading
            with contextlib.suppress(Exception):
                page.mouse.wheel(0, -random.randint(120, 260))
            sleep(0.4 * slow, 0.9 * slow)
    if settle:
        sleep(1.0 * slow, 2.0 * slow)
