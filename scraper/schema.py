"""Output schemas and Algolia-hit -> row mappers, per vertical.

The PROPERTY schema reproduces the exact 30 columns of the user's existing
snapshot (Code repo/codebuddy/data/*.csv) so old and new data are
interchangeable. MOTORS and CLASSIFIEDS use analogous schemas.

Mappers are intentionally defensive: dubizzle's Algolia hit field names are
confirmed from the live `sample_hit` captured by bootstrap_keys.py, and any
field we cannot find degrades to "" rather than raising. The raw sample hit is
stored in config/keys.json so the mapping can be tightened without re-crawling.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
IMAGE_HOST_HINT = "dbz-images"
_IMG_EXT = re.compile(r"\.(jpe?g|png|webp|avif)(\?|$)", re.I)


def first(hit: dict, *keys, default=""):
    """Return the first present, non-empty value among dotted key paths."""
    for key in keys:
        cur = hit
        ok = True
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, "", [], {}):
            return cur
    return default


def _to_epoch_date(value) -> str:
    """Best-effort 'YYYY-MM-DD' from an epoch (s or ms) or ISO string."""
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            n = int(value)
            if n > 10_000_000_000:  # milliseconds
                n //= 1000
            return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%d")
        return str(value)[:10]
    except Exception:
        return ""


def extract_image_urls(hit: dict, limit: int = 60) -> list[str]:
    """Pull original image URLs from a hit, robust to the exact field shape."""
    urls: list[str] = []

    def add(u):
        if isinstance(u, str) and u.startswith("http") and u not in urls:
            urls.append(u)

    # Common explicit locations first (keeps ordering meaningful).
    cover = hit.get("coverPhoto") or hit.get("mainImage") or hit.get("cover_photo")
    if isinstance(cover, dict):
        add(first(cover, "url", "full", "src", "main", default=""))
    elif isinstance(cover, str):
        add(cover)

    for key in ("photos", "images", "gallery", "media", "pictures"):
        seq = hit.get(key)
        if isinstance(seq, list):
            for item in seq:
                if isinstance(item, dict):
                    add(first(item, "url", "full", "src", "main", "href", default=""))
                elif isinstance(item, str):
                    add(item)

    # Fallback: walk the whole hit for any image-looking URL string.
    if not urls:
        def walk(node):
            if isinstance(node, str):
                if node.startswith("http") and (IMAGE_HOST_HINT in node or _IMG_EXT.search(node)):
                    add(node)
            elif isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(hit)

    return urls[:limit]


def coords(hit: dict) -> tuple[str, str]:
    geo = hit.get("_geoloc") or hit.get("geography") or hit.get("location_coordinates") or {}
    if isinstance(geo, list) and geo:
        geo = geo[0]
    if isinstance(geo, dict):
        lat = geo.get("lat", geo.get("latitude", ""))
        lng = geo.get("lng", geo.get("lon", geo.get("longitude", "")))
        return ("" if lat is None else lat, "" if lng is None else lng)
    return ("", "")


def location_name(hit: dict) -> str:
    loc = hit.get("location") or hit.get("locations") or hit.get("geography")
    if isinstance(loc, list):
        names = [x.get("name") for x in loc if isinstance(x, dict) and x.get("name")]
        if names:
            return ", ".join(names)
    if isinstance(loc, dict) and loc.get("name"):
        return loc["name"]
    return first(hit, "city", "neighbourhood", "site", default="")


def _image_columns(urls: list[str], n: int = 10) -> dict:
    out = {f"images/{i}": (urls[i] if i < len(urls) else "") for i in range(n)}
    out["images"] = json.dumps(urls) if urls else ""
    return out


# --------------------------------------------------------------------------- #
# PROPERTY — exact existing 30-column schema
# --------------------------------------------------------------------------- #
PROPERTY_COLUMNS = [
    "title", "url", "price", "bedrooms", "bathrooms", "size", "location",
    "description", "addedOn", "propertyType", "purpose", "furnished", "updatedAt",
    "images/0", "images/1", "images/2", "images/3", "images/4", "images/5",
    "images/6", "images/7", "images/8", "images/9",
    "coordinates/lat", "coordinates/lng", "isVerified", "hasDLDHistory",
    "completionStatus", "propertyReference", "images",
]


def map_property(hit: dict) -> dict:
    lat, lng = coords(hit)
    urls = extract_image_urls(hit)
    purpose = str(first(hit, "purpose", "purpose.slug", default="")).replace("for-", "").title()
    row = {
        "title": first(hit, "title", "title_l1", "name", "title.en"),
        "url": first(hit, "url", "share_url", "permalink", "shareUrl", "absolute_url"),
        "price": first(hit, "price", "price.value", default=""),
        "bedrooms": first(hit, "rooms", "bedrooms", "beds", default=""),
        "bathrooms": first(hit, "baths", "bathrooms", default=""),
        "size": first(hit, "area", "size", "builtUpArea", "plotArea", default=""),
        "location": location_name(hit),
        "description": first(hit, "description", "description_l1", "details"),
        "addedOn": _to_epoch_date(first(hit, "createdAt", "added_on", "created_at", "reactivatedAt")),
        "propertyType": first(hit, "propertyType", "category.name", "categoryName", default=""),
        "purpose": purpose,
        "furnished": first(hit, "furnishingStatus", "furnished", default=""),
        "updatedAt": first(hit, "updatedAt", "reactivatedAt", "updated_at", "lastUpdated", default=""),
        "coordinates/lat": lat,
        "coordinates/lng": lng,
        "isVerified": first(hit, "isVerified", "verified", "verification.status", default=""),
        "hasDLDHistory": first(hit, "hasTransactionHistory", "hasDLDHistory", "dld", default=""),
        "completionStatus": first(hit, "completionStatus", "completion_status", default=""),
        "propertyReference": first(hit, "referenceNumber", "reference", "permitNumber", "propertyReference", default=""),
    }
    row.update(_image_columns(urls))
    return row


# --------------------------------------------------------------------------- #
# MOTORS
# --------------------------------------------------------------------------- #
MOTORS_COLUMNS = [
    "title", "url", "price", "make", "model", "trim", "year", "kilometers",
    "fuelType", "transmission", "bodyType", "color", "location", "description",
    "addedOn", "updatedAt", "sellerType", "isVerified",
    "images/0", "images/1", "images/2", "images/3", "images/4", "images/5",
    "images/6", "images/7", "images/8", "images/9",
    "coordinates/lat", "coordinates/lng", "reference", "images",
]


def map_motors(hit: dict) -> dict:
    lat, lng = coords(hit)
    urls = extract_image_urls(hit)
    row = {
        "title": first(hit, "title", "name", "title_l1"),
        "url": first(hit, "url", "share_url", "permalink", "absolute_url"),
        "price": first(hit, "price", "price.value", default=""),
        "make": first(hit, "make", "brand", "details.make", default=""),
        "model": first(hit, "model", "details.model", default=""),
        "trim": first(hit, "trim", "details.trim", default=""),
        "year": first(hit, "year", "details.year", "modelYear", default=""),
        "kilometers": first(hit, "kilometers", "mileage", "details.kilometers", default=""),
        "fuelType": first(hit, "fuelType", "fuel_type", "details.fuelType", default=""),
        "transmission": first(hit, "transmission", "details.transmission", default=""),
        "bodyType": first(hit, "bodyType", "body_type", "details.bodyType", default=""),
        "color": first(hit, "color", "exteriorColor", "details.color", default=""),
        "location": location_name(hit),
        "description": first(hit, "description", "description_l1"),
        "addedOn": _to_epoch_date(first(hit, "createdAt", "created_at", "reactivatedAt")),
        "updatedAt": first(hit, "updatedAt", "reactivatedAt", "updated_at", default=""),
        "sellerType": first(hit, "sellerType", "seller_type", "agency.type", default=""),
        "isVerified": first(hit, "isVerified", "verified", default=""),
        "coordinates/lat": lat,
        "coordinates/lng": lng,
        "reference": first(hit, "referenceNumber", "reference", "id", "objectID", default=""),
    }
    row.update(_image_columns(urls))
    return row


# --------------------------------------------------------------------------- #
# CLASSIFIEDS (everything else: electronics, furniture, jobs, services, ...)
# --------------------------------------------------------------------------- #
CLASSIFIEDS_COLUMNS = [
    "title", "url", "price", "category", "subCategory", "condition", "location",
    "description", "addedOn", "updatedAt", "sellerType", "isVerified",
    "images/0", "images/1", "images/2", "images/3", "images/4", "images/5",
    "images/6", "images/7", "images/8", "images/9",
    "coordinates/lat", "coordinates/lng", "reference", "images",
]


def map_classifieds(hit: dict) -> dict:
    lat, lng = coords(hit)
    urls = extract_image_urls(hit)
    row = {
        "title": first(hit, "title", "name", "title_l1"),
        "url": first(hit, "url", "share_url", "permalink", "absolute_url"),
        "price": first(hit, "price", "price.value", default=""),
        "category": first(hit, "category.name", "categoryName", "category", default=""),
        "subCategory": first(hit, "subCategory", "subcategory", "category.slug", default=""),
        "condition": first(hit, "condition", "itemCondition", "details.condition", default=""),
        "location": location_name(hit),
        "description": first(hit, "description", "description_l1"),
        "addedOn": _to_epoch_date(first(hit, "createdAt", "created_at", "reactivatedAt")),
        "updatedAt": first(hit, "updatedAt", "reactivatedAt", "updated_at", default=""),
        "sellerType": first(hit, "sellerType", "seller_type", default=""),
        "isVerified": first(hit, "isVerified", "verified", default=""),
        "coordinates/lat": lat,
        "coordinates/lng": lng,
        "reference": first(hit, "referenceNumber", "reference", "id", "objectID", default=""),
    }
    row.update(_image_columns(urls))
    return row


MAPPERS = {
    "property": (PROPERTY_COLUMNS, map_property),
    "motors": (MOTORS_COLUMNS, map_motors),
    "classifieds": (CLASSIFIEDS_COLUMNS, map_classifieds),
}
