"""Per-vertical seed result URLs to crawl.

Each seed is (category_label, results_url). The crawler paginates each url
(`?page=N`) and rows are written to data/<vertical>/<category_label>.csv.gz.
URLs verified to return listing cards (note property rent uses `apartmentflat`,
sale uses `apartment`). Expand these lists over time — the Action crawls slowly.
"""

from __future__ import annotations

from .schema import MAPPERS

BASE = "https://uae.dubizzle.com"

VERTICALS = {
    "property": {
        "enabled": True,
        "seeds": [
            ("residential-for-rent", f"{BASE}/property-for-rent/residential/"),
            ("apartments-for-rent", f"{BASE}/property-for-rent/residential/apartmentflat/"),
            ("villas-for-rent", f"{BASE}/property-for-rent/residential/villahouse/"),
            ("townhouses-for-rent", f"{BASE}/property-for-rent/residential/townhouse/"),
            ("rooms-flatmates", f"{BASE}/property-for-rent/rooms-for-rent-flatmates/"),
            ("short-term-daily", f"{BASE}/property-for-rent/short-term-daily/"),
            ("commercial-for-rent", f"{BASE}/property-for-rent/commercial/"),
            ("apartments-for-sale", f"{BASE}/property-for-sale/residential/apartment/"),
            ("villas-for-sale", f"{BASE}/property-for-sale/residential/villahouse/"),
            ("commercial-for-sale", f"{BASE}/property-for-sale/commercial/"),
            ("land-for-sale", f"{BASE}/property-for-sale/land/"),
        ],
    },
    "motors": {
        "enabled": True,
        "seeds": [
            ("used-cars", f"{BASE}/motors/used-cars/"),
            ("motorcycles", f"{BASE}/motors/motorcycles/"),
            ("auto-accessories-parts", f"{BASE}/motors/auto-accessories-parts/"),
            ("heavy-vehicles", f"{BASE}/motors/heavy-vehicles/"),
            ("boats", f"{BASE}/motors/boats/"),
            ("number-plates", f"{BASE}/motors/number-plates/"),
        ],
    },
    "classifieds": {
        "enabled": True,
        "seeds": [
            ("mobile-phones", f"{BASE}/classified/mobile-phones-pdas/mobile-phones/"),
            ("electronics", f"{BASE}/classified/electronics/"),
            ("computers-networking", f"{BASE}/classified/computers-networking/"),
            ("furniture", f"{BASE}/classified/furniture-home-garden/furniture/"),
            ("home-appliances", f"{BASE}/classified/home-appliances/"),
            ("clothing-accessories", f"{BASE}/classified/clothing-accessories/"),
        ],
    },
}


def columns_for(vertical: str):
    return MAPPERS[vertical][0]


def mapper_for(vertical: str):
    return MAPPERS[vertical][1]
