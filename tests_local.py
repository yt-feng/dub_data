"""Offline self-tests (no network). Run: python tests_local.py"""
import json

from scraper.proxy import usable_proxies_from_subscription, normalize_proxy
from scraper.extract import normalize
from scraper.schema import map_property, map_motors

ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok = ok and cond


# 1. proxy subscription decode (plaintext + base64), vmess skipped
plain = b"http://user:pass@1.2.3.4:8080\nsocks5://5.6.7.8:1080\nvmess://ignored"
check("decode plaintext proxies", usable_proxies_from_subscription(plain) ==
      ["http://user:pass@1.2.3.4:8080", "socks5h://5.6.7.8:1080"])
import base64 as _b64
check("decode base64 subscription",
      usable_proxies_from_subscription(_b64.b64encode(b"http://9.9.9.9:3128\n")) == ["http://9.9.9.9:3128"])
check("normalize socks5->socks5h", normalize_proxy("socks5://h:1") == "socks5h://h:1")

# 2. extract.normalize parses specs out of card text
card = {
    "url": "https://uae.dubizzle.com/property-for-rent/residential/apartments/abc-1234567/",
    "title": "Spacious 2 BR Apartment",
    "price_text": "AED 95,000",
    "images": ["https://dbz-images.dubizzle.com/a/1.jpg", "https://dbz-images.dubizzle.com/a/2.jpg"],
    "text": "AED 95,000 Yearly 2 Bedrooms 3 Bathrooms 1,250 sqft Dubai Marina Verified",
}
n = normalize(dict(card))
check("parse price", n["price"] == 95000)
check("parse bedrooms", n["bedrooms"] == 2)
check("parse bathrooms", n["bathrooms"] == 3)
check("parse size sqft", n["size"] == 1250)

car = normalize({"price_text": "AED 72,500", "text": "AED 72,500 2019 85,000 km Toyota Camry Dubai"})
check("parse car price", car["price"] == 72500)
check("parse car year", car["year"] == 2019)
check("parse car km", car["kilometers"] == 85000)

# 3. schema mappers from a normalized card
n["category"] = "apartments-for-rent"
row = map_property(n)
check("property purpose from category", row["purpose"] == "Rent")
check("property title", row["title"] == "Spacious 2 BR Apartment")
check("property images/0", row["images/0"].endswith("1.jpg"))
check("property images json len 2", len(json.loads(row["images"])) == 2)
check("property column set", set(row) >= {"title", "url", "price", "images/9", "images", "coordinates/lat"})

mrow = map_motors(car)
check("motors year column", mrow["year"] == 2019)

print("\nALL PASS" if ok else "\nSOME FAILED")
raise SystemExit(0 if ok else 1)
