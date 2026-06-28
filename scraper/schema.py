"""Output schemas + mappers from extracted DOM cards to rows.

Property reuses the original 30-column layout (Code repo/codebuddy/data/*.csv)
so old and new data stay interchangeable; fields not present on a result card
(coordinates, reference, DLD history, …) are left blank and can be enriched from
detail pages later. Motors/classifieds use analogous, simpler schemas. Images
are stored as original URLs only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _image_columns(urls: list[str], n: int = 10) -> dict:
    urls = urls or []
    out = {f"images/{i}": (urls[i] if i < len(urls) else "") for i in range(n)}
    out["images"] = json.dumps(urls) if urls else ""
    return out


# --------------------------------------------------------------------------- #
# PROPERTY — original 30-column schema
# --------------------------------------------------------------------------- #
PROPERTY_COLUMNS = [
    "title", "url", "price", "bedrooms", "bathrooms", "size", "location",
    "description", "addedOn", "propertyType", "purpose", "furnished", "updatedAt",
    "images/0", "images/1", "images/2", "images/3", "images/4", "images/5",
    "images/6", "images/7", "images/8", "images/9",
    "coordinates/lat", "coordinates/lng", "isVerified", "hasDLDHistory",
    "completionStatus", "propertyReference", "images",
]


def map_property(card: dict) -> dict:
    cat = card.get("category", "")
    purpose = "Rent" if "rent" in str(cat).lower() else ("Sale" if "sale" in str(cat).lower() else "")
    row = {
        "title": card.get("title", ""),
        "url": card.get("url", ""),
        "price": card.get("price", ""),
        "bedrooms": card.get("bedrooms", ""),
        "bathrooms": card.get("bathrooms", ""),
        "size": card.get("size", ""),
        "location": card.get("location", ""),
        "description": "",
        "addedOn": _today(),
        "propertyType": card.get("property_type", ""),
        "purpose": purpose,
        "furnished": "",
        "updatedAt": "",
        "coordinates/lat": "",
        "coordinates/lng": "",
        "isVerified": card.get("is_verified", ""),
        "hasDLDHistory": "",
        "completionStatus": "",
        "propertyReference": "",
    }
    row.update(_image_columns(card.get("images")))
    return row


# --------------------------------------------------------------------------- #
# MOTORS
# --------------------------------------------------------------------------- #
MOTORS_COLUMNS = [
    "title", "url", "price", "year", "kilometers", "make", "model", "location",
    "addedOn", "images/0", "images/1", "images/2", "images/3", "images/4",
    "images/5", "images/6", "images/7", "images/8", "images/9", "images",
]


def map_motors(card: dict) -> dict:
    row = {
        "title": card.get("title", ""),
        "url": card.get("url", ""),
        "price": card.get("price", ""),
        "year": card.get("year", ""),
        "kilometers": card.get("kilometers", ""),
        "make": card.get("make", ""),
        "model": card.get("model", ""),
        "location": card.get("location", ""),
        "addedOn": _today(),
    }
    row.update(_image_columns(card.get("images")))
    return row


# --------------------------------------------------------------------------- #
# CLASSIFIEDS
# --------------------------------------------------------------------------- #
CLASSIFIEDS_COLUMNS = [
    "title", "url", "price", "category", "location", "addedOn",
    "images/0", "images/1", "images/2", "images/3", "images/4",
    "images/5", "images/6", "images/7", "images/8", "images/9", "images",
]


def map_classifieds(card: dict) -> dict:
    row = {
        "title": card.get("title", ""),
        "url": card.get("url", ""),
        "price": card.get("price", ""),
        "category": card.get("category", ""),
        "location": card.get("location", ""),
        "addedOn": _today(),
    }
    row.update(_image_columns(card.get("images")))
    return row


MAPPERS = {
    "property": (PROPERTY_COLUMNS, map_property),
    "motors": (MOTORS_COLUMNS, map_motors),
    "classifieds": (CLASSIFIEDS_COLUMNS, map_classifieds),
}
