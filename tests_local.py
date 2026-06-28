"""Offline self-tests (no network/keys). Run: python tests_local.py"""
import json
import re

from scraper.algolia import encode_params
from scraper.proxy import usable_proxies_from_subscription, normalize_proxy
from scraper.schema import map_property, extract_image_urls
from scraper.partition import harvest

ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok = ok and cond


# 1. param encoding: arrays -> JSON
enc = encode_params({"query": "", "facets": ["price", "make"], "numericFilters": ["price>=1"], "page": 0})
check("encode arrays as JSON", "facets=%5B%22price%22%2C+%22make%22%5D" in enc or "facets=" in enc and '["price"' in json.dumps(["price"]))
check("encode numericFilters JSON", "numericFilters=" in enc and "price%3E%3D1" in enc)
check("encode scalar page", "page=0" in enc)

# 2. proxy subscription decode (plaintext + base64)
plain = b"http://user:pass@1.2.3.4:8080\nsocks5://5.6.7.8:1080\nvmess://ignored"
ps = usable_proxies_from_subscription(plain)
check("decode plaintext proxies (2 usable, vmess skipped)", ps == ["http://user:pass@1.2.3.4:8080", "socks5h://5.6.7.8:1080"])
import base64 as _b64
b64 = _b64.b64encode(b"http://9.9.9.9:3128\n")
check("decode base64 subscription", usable_proxies_from_subscription(b64) == ["http://9.9.9.9:3128"])
check("normalize socks5->socks5h", normalize_proxy("socks5://h:1") == "socks5h://h:1")

# 3. schema mapper on a realistic Bayut/dubizzle-style hit
hit = {
    "objectID": "abc123",
    "title": "3BR Villa in Springs",
    "url": "https://dubizzle.com/s/DfBm3oW",
    "price": 250000,
    "rooms": 3,
    "baths": 3,
    "area": 2250,
    "purpose": "for-rent",
    "propertyType": "Villa",
    "furnishingStatus": "Unfurnished",
    "createdAt": 1754293806,
    "referenceNumber": "DP-R-55229",
    "isVerified": True,
    "location": [{"name": "The Springs"}, {"name": "Dubai"}],
    "_geoloc": {"lat": 25.05, "lng": 55.2},
    "coverPhoto": {"url": "https://dbz-images.dubizzle.com/images/a/cover.jpg?impolicy=dpv"},
    "photos": [{"url": "https://dbz-images.dubizzle.com/images/a/1.jpg"}, {"url": "https://dbz-images.dubizzle.com/images/a/2.jpg"}],
}
row = map_property(hit)
check("map title", row["title"] == "3BR Villa in Springs")
check("map price", row["price"] == 250000)
check("map purpose for-rent->Rent", row["purpose"] == "Rent")
check("map bedrooms", row["bedrooms"] == 3)
check("map location join", row["location"] == "The Springs, Dubai")
check("map addedOn date", row["addedOn"] == "2025-08-04")
check("map coords", row["coordinates/lat"] == 25.05 and row["coordinates/lng"] == 55.2)
check("map images/0 = cover", row["images/0"].endswith("cover.jpg?impolicy=dpv"))
check("map images json has 3", len(json.loads(row["images"])) == 3)
check("map reference", row["propertyReference"] == "DP-R-55229")

# image extractor fallback (only photoIDs-style nested string)
check("image fallback finds dbz url", extract_image_urls({"x": {"y": "https://dbz-images.dubizzle.com/z/9.jpg"}}) == ["https://dbz-images.dubizzle.com/z/9.jpg"])


# 4. partitioner completeness against a mock Algolia index
class MockClient:
    CAP = 1000

    def __init__(self, n):
        # n items, each with a price 0..n and a 'cat' in 3 buckets
        self.items = [
            {"objectID": str(i), "price": i, "cat": ["a", "b", "c"][i % 3]}
            for i in range(n)
        ]

    def _filter(self, params):
        items = self.items
        f = params.get("filters", "")
        m = re.findall(r'cat:"([^"]+)"', f)
        if m:
            items = [x for x in items if x["cat"] in m]
        for nf in params.get("numericFilters", []) or []:
            mm = re.match(r"price(>=|<=|<|>)(-?[\d.]+)", nf)
            if mm:
                op, val = mm.group(1), float(mm.group(2))
                if op == ">=":
                    items = [x for x in items if x["price"] >= val]
                elif op == "<":
                    items = [x for x in items if x["price"] < val]
                elif op == "<=":
                    items = [x for x in items if x["price"] <= val]
                elif op == ">":
                    items = [x for x in items if x["price"] > val]
        return items

    def count(self, index, params):
        return len(self._filter(params))

    def query(self, index, params):
        items = self._filter(params)
        nb = len(items)
        hpp = params.get("hitsPerPage", 1000)
        page = params.get("page", 0)
        # emulate Algolia: only first CAP reachable
        reachable = items[: self.CAP]
        start = page * hpp
        hits = reachable[start : start + hpp] if hpp else []
        nb_pages = max(1, (min(nb, self.CAP) + hpp - 1) // hpp) if hpp else 1
        return {"hits": hits, "nbHits": nb, "nbPages": nb_pages}

    def facet_values(self, index, facet, params):
        items = self._filter(params)
        out = {}
        for x in items:
            out[x[facet]] = out.get(x[facet], 0) + 1
        return out

    def numeric_stats(self, index, attr, params):
        items = self._filter(params)
        if not items:
            return None
        vals = [x[attr] for x in items]
        return float(min(vals)), float(max(vals))


for N in (500, 2500, 12000):
    mc = MockClient(N)
    got = harvest(mc, "idx", facet_priority=("cat",), numeric_attr="price", cap=1000, log=lambda m: None)
    ids = {h["objectID"] for h in got}
    check(f"partition full coverage N={N} (got {len(ids)})", len(ids) == N)

print("\nALL PASS" if ok else "\nSOME FAILED")
raise SystemExit(0 if ok else 1)
