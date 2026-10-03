"""Listing sources: a mock file for offline runs, and the Apify Homegate actor
for live data. Both yield listings in one normalized shape."""

from __future__ import annotations

import json
import os
import urllib.request

from .config import ALLOWED_CANTONS, FILTERS, DATA_DIR, passes_bounds

APIFY_ENDPOINT = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


def _norm(listing: dict) -> dict:
    return {
        "listing_id": str(listing.get("listing_id") or listing.get("url", "")),
        "url": listing.get("url", ""),
        "canton": listing.get("canton", ""),
        "municipality": listing.get("municipality", ""),
        "postal_code": str(listing.get("postal_code", "") or ""),
        "price_chf": listing.get("price_chf"),
        "rooms": listing.get("rooms"),
        "living_area_m2": listing.get("living_area_m2"),
        "year_built": listing.get("year_built"),
        "title": listing.get("title", ""),
        "description": listing.get("description", ""),
    }


def fetch_mock(canton: str, fixtures_path: str):
    with open(fixtures_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    for item in raw:
        if item.get("canton") != canton:
            continue
        lst = _norm(item)
        if passes_bounds(lst["rooms"], lst["price_chf"]):
            yield lst


def _dig(d, path, default=None):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur


def fetch_apify(canton: str):
    token = os.environ.get("APIFY_TOKEN", "")
    if not token:
        raise RuntimeError("APIFY_TOKEN is not set")
    actor = os.environ.get("APIFY_ACTOR", "ducto~homegate-property-scraper")
    location = ALLOWED_CANTONS.get(canton, {}).get("name", canton)
    payload = json.dumps({
        "locations": [location],
        "offerType": "BUY",
        "priceMax": FILTERS["price_max"],
        "roomsMin": FILTERS["rooms_min"],
        "roomsMax": FILTERS["rooms_max"],
        "livingSpaceMax": FILTERS["living_max"],
        "outputLanguage": "de",
        "maxItems": 200,
        "proxyConfiguration": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
            "apifyProxyCountry": "CH",
        },
    }).encode("utf-8")
    url = APIFY_ENDPOINT.format(actor=actor) + f"?token={token}&timeout=300"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=360) as resp:
            items = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Apify fetch failed for {canton}: {exc}") from exc
    if not isinstance(items, list):
        return
    for item in items:
        if str(item.get("offerType", "BUY")).upper() == "RENT":
            continue
        lst = _norm({
            "listing_id": item.get("propertyId") or item.get("url", ""),
            "url": item.get("url", ""),
            "canton": _dig(item, "address.region", ""),
            "municipality": _dig(item, "address.locality", ""),
            "postal_code": _dig(item, "address.postalCode", ""),
            "price_chf": item.get("price"),
            "rooms": _dig(item, "characteristics.numberOfRooms"),
            "living_area_m2": _dig(item, "characteristics.livingSpaceSqm"),
            "year_built": _dig(item, "characteristics.yearBuilt"),
            "title": item.get("title", ""),
            "description": item.get("description", ""),
        })
        if passes_bounds(lst["rooms"], lst["price_chf"]):
            yield lst


def fetch(source: str, canton: str):
    if source == "mock":
        return fetch_mock(canton, os.path.join(DATA_DIR, "sample_listings.json"))
    if source == "apify":
        return fetch_apify(canton)
    raise SystemExit(f"unknown source: {source}")
