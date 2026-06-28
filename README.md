# dub_data

Daily snapshot of [dubizzle.com](https://www.dubizzle.com/) listings — **property, motors, and classifieds** — committed to this repo as gzipped CSV. Images are stored as **original URLs only** (never downloaded).

## How it works

dubizzle's web pages sit behind **Imperva/Incapsula**, which blocks datacenter IPs (so a plain scraper on a GitHub-hosted runner gets a "Pardon Our Interruption" page). But the listings themselves are served by an **Algolia** search backend that is reachable from anywhere — it just needs the site's current public search key.

So the pipeline has two stages, run daily by [`.github/workflows/daily-scrape.yml`](.github/workflows/daily-scrape.yml):

1. **Key bootstrap** ([`scraper/bootstrap_keys.py`](scraper/bootstrap_keys.py)) — a headless Chromium routed through a **proxy** (non-datacenter IP) opens one listing page per vertical and captures the Algolia request it fires: `appId`, public `apiKey`, `host`, `indexName`, the facets the site uses, and a sample hit. Saved to [`config/keys.json`](config/keys.json). This re-runs every execution, so a **rotated key is picked up automatically** — nothing is hardcoded.
2. **Harvest** ([`scraper/main.py`](scraper/main.py)) — queries Algolia directly with those keys and writes the data.

### Getting *everything* despite Algolia's 1000-result cap

Algolia won't page past 1000 results per query. [`scraper/partition.py`](scraper/partition.py) recursively splits the query space until every slice has < 1000 hits, then pages each slice:

- **facet drill-down** (category → purpose → type, or make → model → year, …), then
- **numeric bisection** on `price` when facets are exhausted.

Hits are de-duplicated by `objectID`, so slice overlap is harmless. A coverage check (`nbHits` total vs rows collected) confirms nothing is truncated.

## Setup

This repo needs one secret — a **proxy subscription** that yields a residential / non-datacenter IP (the same kind used by the `bbg-show` repo):

- Repo → Settings → Secrets and variables → Actions → **New repository secret**
- Name: `DUBIZZLE_PROXY_SUBSCRIPTION_URL`
- Value: your subscription URL (plain list of `http(s)://`/`socks5://` proxies, or a base64 blob of them)

Alternatively set `DUBIZZLE_PROXY_SUBSCRIPTION` with the inline content.

Then enable Actions and either wait for the daily cron (03:00 UTC) or trigger **Run workflow** manually.

## Data layout

```
data/
  property/<purpose>__<type>.csv.gz     # 30-col schema, identical to the original snapshot
  motors/<make>.csv.gz
  classifieds/<category>.csv.gz
  summary.json                          # per-vertical counts, run time, key fingerprint
config/keys.json                        # auto-refreshed Algolia creds + sample hit
```

The **property** schema reproduces the original columns exactly:
`title, url, price, bedrooms, bathrooms, size, location, description, addedOn, propertyType, purpose, furnished, updatedAt, images/0…9, coordinates/lat, coordinates/lng, isVerified, hasDLDHistory, completionStatus, propertyReference, images`.

## Run locally

```bash
pip install -r requirements.txt
python -m playwright install chromium

export DUBIZZLE_PROXY_SUBSCRIPTION_URL="https://…"   # your proxy subscription

# quick test: 200 records of property only
python -m scraper.main --vertical property --limit 200

# full run, all verticals
python -m scraper.main
```

Useful flags: `--no-bootstrap` (reuse cached `config/keys.json`), `--no-proxy` (try direct — only works from a residential IP), `--proxy-harvest` (route Algolia calls through the proxy too), `--sleep 0.2`.

### Seeding keys without a proxy (manual fallback)

If you can't supply a proxy, capture the keys from your own browser. On a dubizzle listing page (e.g. property), open DevTools → Network, filter `algolia`, reload, click the `*/queries` request and read:

- Request URL host → `host`, and query/header `x-algolia-application-id` → `app_id`, `x-algolia-api-key` → `api_key`
- Request payload `requests[0].indexName` → `index`

Put them into `config/keys.json`:

```json
{
  "property": {"host": "…-dsn.algolia.net", "app_id": "…", "api_key": "…", "index": "…", "facets": []}
}
```

Then run with `--no-bootstrap`. (Scheduled runs still refresh keys via the proxy.)

## Notes / tuning

- **Volume.** Whole-site classifieds is large and the harvest is request-heavy. Each vertical can be toggled in [`scraper/verticals.py`](scraper/verticals.py) (`enabled`), and the snapshot is overwritten daily to keep git history bounded. If a full run exceeds the 6h Actions limit, split verticals across separate scheduled runs.
- **Field mapping.** Mappers in [`scraper/schema.py`](scraper/schema.py) are defensive and refined from the live `sample_hit` recorded in `config/keys.json`. If a column comes through empty, check that sample hit and adjust the field path.
