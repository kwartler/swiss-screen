"""Listing sources: a mock file for offline runs, the public Flatfox API for
live data (the default), and the Apify Homegate actor (blocked by Homegate's
bot protection without residential proxies). All yield listings in one
normalized shape."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .config import ALLOWED_CANTONS, FILTERS, DATA_DIR, locate_postcode, passes_bounds

APIFY_ENDPOINT = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
FLATFOX_BASE = "https://flatfox.ch"
FLATFOX_ENDPOINT = FLATFOX_BASE + "/api/v1/public-listing/?limit=100"
FLATFOX_CATEGORIES = {"APARTMENT", "HOUSE"}
USER_AGENT = "swiss-screen (+https://github.com/kwartler/swiss-screen)"


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
    url = APIFY_ENDPOINT.format(actor=actor) + "?timeout=300"
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req, timeout=360) as resp:
            items = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Apify explains rejections in the body (bad token, plan limit, etc.).
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Apify fetch failed for {canton}: {exc} {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Apify fetch failed for {canton}: {exc}") from exc
    if not isinstance(items, list):
        print(f"[{canton}] Apify returned non-list response: {json.dumps(items)[:500]}")
        return
    print(f"[{canton}] Apify returned {len(items)} raw items")
    if items:
        print(f"[{canton}] sample item: {json.dumps(items[0], ensure_ascii=False)[:800]}")
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


def _get_json(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Flatfox fetch failed: {exc}") from exc
            time.sleep(5 * (attempt + 1))


_FLATFOX_SALES = None


def _flatfox_sales():
    """All Flatfox SALE listings, normalized. The API has no sale or canton
    filter, so the full feed (~360 pages) is paged once per run and shared
    across cantons."""
    global _FLATFOX_SALES
    if _FLATFOX_SALES is not None:
        return _FLATFOX_SALES
    sales, url, pages = [], FLATFOX_ENDPOINT, 0
    while url:
        page = _get_json(url)
        pages += 1
        for item in page.get("results", []):
            if item.get("offer_type") != "SALE":
                continue
            if item.get("object_category") not in FLATFOX_CATEGORIES:
                continue
            if item.get("price_display_type") not in (None, "TOTAL"):
                continue
            sales.append(_flatfox_norm(item))
        url = page.get("next")
    print(f"Flatfox: paged {pages} pages, {len(sales)} apartment/house sales")
    _FLATFOX_SALES = sales
    return sales


def _flatfox_norm(item):
    commune, canton = locate_postcode(item.get("zipcode"), item.get("city", ""))
    canton = (item.get("state") or canton or "").upper()
    rooms = item.get("number_of_rooms")
    title = item.get("description_title") or item.get("public_title") or item.get("short_title") or ""
    return _norm({
        "listing_id": f"ff-{item.get('pk')}",
        "url": FLATFOX_BASE + (item.get("url") or ""),
        "canton": canton,
        "municipality": commune or item.get("city", ""),
        "postal_code": item.get("zipcode", ""),
        "price_chf": item.get("price_display"),
        "rooms": float(rooms) if rooms else None,
        "living_area_m2": item.get("livingspace") or item.get("surface_living"),
        "year_built": item.get("year_built"),
        "title": title,
        "description": item.get("description", ""),
    })


def fetch_flatfox(canton: str):
    for lst in _flatfox_sales():
        if lst["canton"] != canton:
            continue
        area = lst["living_area_m2"]
        if area and area > FILTERS["living_max"]:
            continue
        if passes_bounds(lst["rooms"], lst["price_chf"]):
            yield lst


def fetch(source: str, canton: str):
    if source == "mock":
        return fetch_mock(canton, os.path.join(DATA_DIR, "sample_listings.json"))
    if source == "flatfox":
        return fetch_flatfox(canton)
    if source == "apify":
        return fetch_apify(canton)
    raise SystemExit(f"unknown source: {source}")
