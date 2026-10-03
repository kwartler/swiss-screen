"""Commune centroids for the map.

Coordinates live in data/commune_coords.csv, keyed by normalized commune name.
A seed file ships with the resort communes so the map works offline on the mock
data. On a real run (for example inside GitHub Actions, which has open egress),
any commune still missing coordinates is looked up once via the OpenStreetMap
Nominatim API, politely and with a cache, so each commune is geocoded at most
once in the life of the repo.

Geocoding is skipped automatically when the network is unreachable (as in a
locked-down sandbox), so the pipeline never blocks on it.
"""

from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
import urllib.request

from .config import DATA_DIR, ckey, resolve_commune

COORDS_PATH = os.path.join(DATA_DIR, "commune_coords.csv")
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "swiss-foreign-property-screen/1.0 (personal research)"


def load_coords() -> dict:
    out = {}
    if not os.path.exists(COORDS_PATH):
        return out
    with open(COORDS_PATH, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = ckey(row.get("commune", ""))
            try:
                out[key] = (float(row["lat"]), float(row["lon"]))
            except (KeyError, ValueError, TypeError):
                continue
    return out


def _save_coords(coords: dict, names: dict) -> None:
    rows = sorted(coords.items())
    with open(COORDS_PATH, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["commune", "lat", "lon"])
        for key, (lat, lon) in rows:
            w.writerow([names.get(key, key), f"{lat:.5f}", f"{lon:.5f}"])


def _nominatim(commune: str):
    params = urllib.parse.urlencode({
        "q": f"{commune}, Switzerland", "format": "json", "limit": 1,
    })
    req = urllib.request.Request(f"{NOMINATIM}?{params}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not data:
        return None
    try:
        return float(data[0]["lat"]), float(data[0]["lon"])
    except (KeyError, ValueError):
        return None


def ensure_coords(communes, allow_network: bool = True) -> dict:
    """Return {ckey: (lat, lon)} for the given commune names, geocoding and
    caching any that are missing. `communes` is an iterable of commune names
    (already resolved from villages where relevant)."""
    coords = load_coords()
    names = {ckey(c): c for c in communes if c}
    # preserve names already in the file
    if os.path.exists(COORDS_PATH):
        with open(COORDS_PATH, "r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                k = ckey(row.get("commune", ""))
                names.setdefault(k, row.get("commune", k))

    missing = [c for c in communes if c and ckey(c) not in coords]
    if missing and allow_network:
        for commune in dict.fromkeys(missing):  # de-dupe, keep order
            latlon = _nominatim(commune)
            if latlon is not None:
                coords[ckey(commune)] = latlon
                names[ckey(commune)] = commune
            time.sleep(1.1)  # Nominatim asks for <= 1 request/second
        _save_coords(coords, names)
    return coords


def coords_for(muni: str, coords: dict):
    """Look up coordinates for a listing municipality (resolving village first)."""
    key = ckey(resolve_commune(muni))
    return coords.get(key)
