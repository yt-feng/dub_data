# dub_data

Daily snapshot of [dubizzle.com](https://www.dubizzle.com/) UAE listings — **property, motors, and classifieds** — committed here as gzipped CSV. Images are stored as **original URLs only** (never downloaded).

## How it works

dubizzle is behind **Imperva**, which (1) blocks datacenter IPs and (2) fingerprints headless/automated browsers, and it **renders listings into the DOM** rather than exposing a clean JSON API. So the scraper:

1. Drives a **real, headful Chromium** ([`scraper/browser.py`](scraper/browser.py)) with automation flags off, waiting for the JS challenge to clear and behaving like a human — gradual randomised scrolling, real pauses ([`human_scroll`](scraper/browser.py)).
2. Extracts each result card from the rendered DOM ([`scraper/extract.py`](scraper/extract.py)), anchored on the price text so it survives class-name churn, then paginates `?page=N` politely ([`scraper/crawl.py`](scraper/crawl.py)).
3. Maps cards to the output schema ([`scraper/schema.py`](scraper/schema.py)) and writes gzipped CSV.

**IP matters.** On a residential IP (your laptop) it runs without a proxy. On GitHub's datacenter runners you **must** route through a residential **proxy** and run **headful under xvfb** — both wired into [`.github/workflows/daily-scrape.yml`](.github/workflows/daily-scrape.yml). The crawl is intentionally slow; daily runs accumulate coverage over time.

> Don't hammer it. Bursty behaviour gets the IP soft-blocked (pages load but return "no results"). Keep `--slow` ≥ 1.5 on shared IPs.

## Setup (one secret)

Add a residential **proxy subscription** (same kind your `bbg-show` repo uses):

- Repo → Settings → Secrets and variables → Actions → **New repository secret**
- Name: `DUBIZZLE_PROXY_SUBSCRIPTION_URL`
- Value: your subscription URL (a list of `http(s)://`/`socks5://` proxies, or a base64 blob of them). Or use `DUBIZZLE_PROXY_SUBSCRIPTION` for inline content.

Then run the **daily-scrape** workflow (cron 03:00 UTC, or **Run workflow** manually).

## Data layout

```
data/
  property/<category>.csv.gz       # property reuses the original 30-column schema
  motors/<category>.csv.gz
  classifieds/<category>.csv.gz
  summary.json                     # per-vertical/category counts + run time
```

Property columns (original layout):
`title, url, price, bedrooms, bathrooms, size, location, description, addedOn, propertyType, purpose, furnished, updatedAt, images/0…9, coordinates/lat, coordinates/lng, isVerified, hasDLDHistory, completionStatus, propertyReference, images`.

Fields available on a result card (title, url, price, beds/baths/size, images) are filled now; the rest (coordinates, reference, DLD history, …) are left blank and can be enriched from detail pages in a later pass.

## Run locally

```bash
pip install -r requirements.txt
python -m playwright install chromium

# small test: 1 page of one property category, slow + human-like (no proxy on home IP)
python -m scraper.main --vertical property --max-pages 1 --slow 1.5

# full run (all verticals)
python -m scraper.main --max-pages 5 --slow 1.5
```

Flags: `--proxy` (use the subscription), `--max-pages N`, `--slow X` (pause scale), `--vertical property|motors|classifieds` (repeatable), `--headless` (residential IPs only).

Seed result URLs live in [`scraper/verticals.py`](scraper/verticals.py) — start small and expand the lists over time.

## Offline tests

```bash
python tests_local.py   # proxy decode, spec parsing, schema mapping
```
