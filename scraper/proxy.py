"""Proxy subscription handling.

Adapted from the user's bbg-show repo (tools/proxy_hls_downloader.py): a
subscription is either a list of proxy URLs or a base64 blob that decodes to
one. We decode it, normalise each node to an http/https/socks5 URL, and pick a
working node by checking egress connectivity.

The picked proxy is used to drive a real browser (Playwright) so we can pass
dubizzle's Imperva/Incapsula anti-bot from a non-datacenter IP. The Algolia
backend itself is reachable without a proxy, but we keep the proxy available as
a fallback for harvesting too.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}

# A neutral endpoint that just echoes the caller IP — used to confirm a proxy
# node is alive and to log the egress IP we will appear as to dubizzle.
EGRESS_CHECK_URL = "https://api.ipify.org?format=json"


# --------------------------------------------------------------------------- #
# Subscription decoding (ported from bbg-show)
# --------------------------------------------------------------------------- #
def decode_subscription(raw: bytes) -> list[str]:
    """Return the list of proxy node strings from a subscription blob."""
    raw = raw.strip()
    try:
        text = raw.decode("utf-8")
        if "://" not in text and re.fullmatch(r"[A-Za-z0-9+/_=\-\s]+", text or ""):
            text = base64.b64decode(raw + b"=" * ((4 - len(raw) % 4) % 4)).decode(
                "utf-8", "ignore"
            )
    except UnicodeDecodeError:
        text = base64.b64decode(raw + b"=" * ((4 - len(raw) % 4) % 4)).decode(
            "utf-8", "ignore"
        )
    return [line.strip() for line in text.splitlines() if line.strip()]


def _proxy_scheme(proxy: str) -> str:
    match = re.match(r"^([a-z0-9+.-]+)://", proxy.lower())
    return match.group(1) if match else ""


def _strip_label(proxy: str) -> str:
    parts = urlsplit(proxy)
    if not parts.scheme:
        return proxy
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _b64decode_text(value: str) -> str | None:
    try:
        padded = value + "=" * ((4 - len(value) % 4) % 4)
        return base64.b64decode(padded).decode("utf-8", "ignore")
    except Exception:
        return None


def _without_path(proxy: str) -> str:
    parts = urlsplit(proxy)
    if not parts.scheme or not parts.netloc:
        return proxy
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def normalize_proxy(node: str) -> str | None:
    """Normalise a single subscription line into a usable proxy URL.

    Only http/https/socks5 nodes are usable directly by requests/Playwright;
    vmess/vless/trojan/ss lines (which need a local client) are skipped.
    """
    scheme = _proxy_scheme(node)
    if scheme == "https":
        parts = urlsplit(node)
        payload = node[len("https://") :]
        decoded = None
        if not parts.username and not parts.port and len(payload) > 80:
            decoded = _b64decode_text(payload)
        if decoded:
            return _without_path("https://" + decoded)
        return _without_path(_strip_label(node))
    if scheme in {"http", "socks5", "socks5h"}:
        proxy = _without_path(_strip_label(node))
        if scheme == "socks5":
            proxy = "socks5h://" + proxy[len("socks5://") :]
        return proxy
    return None


def usable_proxies_from_subscription(raw: bytes) -> list[str]:
    out: list[str] = []
    for node in decode_subscription(raw):
        proxy = normalize_proxy(node)
        if proxy and _proxy_scheme(proxy) in SUPPORTED_PROXY_SCHEMES:
            out.append(proxy)
    # de-dup, preserve order
    seen: set[str] = set()
    uniq = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


# --------------------------------------------------------------------------- #
# Loading the subscription from env/file/url
# --------------------------------------------------------------------------- #
def load_subscription_raw() -> bytes | None:
    """Load subscription content from, in priority order:

    1. DUBIZZLE_PROXY_SUBSCRIPTION (inline content)
    2. DUBIZZLE_PROXY_SUBSCRIPTION_URL (fetched over https)
    3. a local file tmp/proxy_sub.raw
    """
    inline = os.environ.get("DUBIZZLE_PROXY_SUBSCRIPTION")
    if inline:
        return inline.encode("utf-8")

    url = os.environ.get("DUBIZZLE_PROXY_SUBSCRIPTION_URL")
    if url:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.content

    local = Path("tmp/proxy_sub.raw")
    if local.exists():
        return local.read_bytes()

    return None


# --------------------------------------------------------------------------- #
# Node selection
# --------------------------------------------------------------------------- #
def _requests_proxies(proxy: str) -> dict[str, str]:
    return {"http": proxy, "https": proxy}


def check_proxy(proxy: str, timeout: int = 15) -> str | None:
    """Return the egress IP if the proxy works, else None."""
    try:
        resp = requests.get(
            EGRESS_CHECK_URL,
            proxies=_requests_proxies(proxy),
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.ok:
            return resp.json().get("ip")
    except Exception:
        return None
    return None


def pick_working_proxy(
    proxies: list[str] | None = None, max_tries: int = 20
) -> tuple[str, str] | None:
    """Return (proxy_url, egress_ip) for the first working node, or None.

    If `proxies` is None, the subscription is loaded from the environment.
    """
    if proxies is None:
        raw = load_subscription_raw()
        if not raw:
            return None
        proxies = usable_proxies_from_subscription(raw)

    for proxy in proxies[:max_tries]:
        ip = check_proxy(proxy)
        if ip:
            return proxy, ip
    return None


def playwright_proxy_arg(proxy: str) -> dict[str, str]:
    """Convert a proxy URL into Playwright's proxy config dict.

    Playwright expects {"server": "scheme://host:port", "username":..,
    "password":..}. socks5h is mapped to socks5 (Playwright understands socks5).
    """
    parts = urlsplit(proxy)
    scheme = parts.scheme.replace("socks5h", "socks5")
    server = f"{scheme}://{parts.hostname}"
    if parts.port:
        server += f":{parts.port}"
    cfg = {"server": server}
    if parts.username:
        cfg["username"] = parts.username
    if parts.password:
        cfg["password"] = parts.password
    return cfg


if __name__ == "__main__":
    import json

    picked = pick_working_proxy()
    if not picked:
        print("No working proxy found (set DUBIZZLE_PROXY_SUBSCRIPTION_URL).")
        raise SystemExit(1)
    proxy, ip = picked
    print(json.dumps({"proxy": proxy, "egress_ip": ip, "playwright": playwright_proxy_arg(proxy)}, indent=2))
