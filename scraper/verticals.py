"""Per-vertical configuration.

`listing_urls` are tried in order during key bootstrap until one fires an
Algolia request we can capture. `facet_priority` / `numeric_attr` drive the
partitioner (partition.py). `split_key` decides which output file a mapped row
goes to, so the snapshot is broken into human-meaningful files (mirroring the
original data/ layout for property).

Facet attribute names are best-effort guesses; bootstrap also records the
facets the site itself requested, and main.py prefers those when present.
"""

from __future__ import annotations

from .schema import MAPPERS


def _slug(value: str) -> str:
    return (
        str(value).strip().lower().replace("/", "-").replace(" ", "-").replace("--", "-")
        or "all"
    )


VERTICALS = {
    "property": {
        "enabled": True,
        "listing_urls": [
            "https://www.dubizzle.com/property-for-sale/",
            "https://uae.dubizzle.com/property-for-rent/residential/",
            "https://dubai.dubizzle.com/en/property-for-rent/residential/",
            "https://www.dubizzle.com/property-for-rent/",
        ],
        "facet_priority": ("purpose", "category.slug", "propertyType", "rooms"),
        "numeric_attr": "price",
        "split_key": lambda r: f"{_slug(r.get('purpose') or 'all')}__{_slug(r.get('propertyType') or 'all')}",
    },
    "motors": {
        "enabled": True,
        "listing_urls": [
            "https://www.dubizzle.com/motors/used-cars/",
            "https://uae.dubizzle.com/motors/used-cars/",
            "https://dubai.dubizzle.com/en/motors/used-cars/",
        ],
        "facet_priority": ("make", "model", "year"),
        "numeric_attr": "price",
        "split_key": lambda r: _slug(r.get("make") or "all"),
    },
    "classifieds": {
        "enabled": True,
        "listing_urls": [
            "https://www.dubizzle.com/classified/",
            "https://uae.dubizzle.com/classified/",
            "https://www.dubizzle.com/community/",
        ],
        "facet_priority": ("category.slug", "subCategory", "condition"),
        "numeric_attr": "price",
        "split_key": lambda r: _slug(r.get("category") or "all"),
    },
}


def columns_for(vertical: str):
    return MAPPERS[vertical][0]


def mapper_for(vertical: str):
    return MAPPERS[vertical][1]
