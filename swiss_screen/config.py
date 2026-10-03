"""Regulatory configuration and commune resolution.

Loads the real reference data (ARE second home shares, village to commune map,
tourist overlays) from the data directory and exposes the lookups the rest of
the pipeline needs. Everything is keyed through ckey(), a normalized commune key
that folds umlauts to ae/oe/ue and strips accents, so a listing locality matches
the reference data regardless of spelling.
"""

from __future__ import annotations

import csv
import os
import unicodedata
from functools import lru_cache

DATA_DIR = os.environ.get(
    "DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
)

# ---------------------------------------------------------------------------
# Canton allowlist (the seventeen cantons with a holiday home quota)
# ---------------------------------------------------------------------------

ALLOWED_CANTONS = {
    "VS": {"name": "Valais", "quota": 330},
    "GR": {"name": "Graubuenden", "quota": 290},
    "TI": {"name": "Ticino", "quota": None},
    "VD": {"name": "Vaud", "quota": None},
    "BE": {"name": "Bern", "quota": None},
    "LU": {"name": "Lucerne", "quota": None},
    "SG": {"name": "St. Gallen", "quota": None},
    "FR": {"name": "Fribourg", "quota": None},
    "NE": {"name": "Neuchatel", "quota": None},
    "SZ": {"name": "Schwyz", "quota": None},
    "AR": {"name": "Appenzell Ausserrhoden", "quota": 20},
    "UR": {"name": "Uri", "quota": 20},
    "NW": {"name": "Nidwalden", "quota": 20},
    "OW": {"name": "Obwalden", "quota": 20},
    "GL": {"name": "Glarus", "quota": 20},
    "JU": {"name": "Jura", "quota": 20},
    "SH": {"name": "Schaffhausen", "quota": 20},
}

# All seventeen cantons that permit non-resident holiday-home acquisition.
# Narrow this list to focus the sweep (for example ["VS", "GR", "VD", "BE"]).
PRIMARY_TARGETS = ["VS", "GR", "TI", "VD", "BE", "LU", "SG", "FR", "NE", "SZ",
                   "AR", "UR", "NW", "OW", "GL", "JU", "SH"]

FILTERS = {
    "rooms_min": 1.0,
    "rooms_max": 3.5,
    "price_max": 850000,
    "living_max": 200,
    "plot_max": 1000,
}

RESALE_HOLD = {"VS": 5}  # cantons barring foreign resale within N years

LEX_WEBER_YEAR = 2012
FROZEN_NEAR = 17  # at or above this, up to 20, counts as approaching the line


def ckey(x) -> str:
    """Normalized commune key: lowercase, umlauts to ae/oe/ue, accents stripped."""
    if x is None:
        return ""
    s = str(x).strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


def _read_csv(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Reference data, loaded once
# ---------------------------------------------------------------------------

def _load_commune_share():
    out = {}
    for row in _read_csv("communes.csv"):
        key = ckey(row.get("municipality", ""))
        if not key:
            continue
        try:
            pct = float(row["pct"]) if row.get("pct") not in (None, "") else None
        except ValueError:
            pct = None
        restricted = row.get("restricted", "")
        in_review = str(row.get("in_review", "")).strip().upper() in ("TRUE", "1")
        out[key] = {
            "pct": pct,
            "restricted": int(restricted) if str(restricted).strip() not in ("", "NA") else None,
            "in_review": in_review,
            "canton": (row.get("canton") or "").strip().upper(),
            "name": row.get("municipality", ""),
        }
    return out


def _load_villages():
    out = {}
    for row in _read_csv("villages.csv"):
        loc = ckey(row.get("locality", ""))
        com = (row.get("commune") or "").strip()
        if loc and com:
            out[loc] = com
    return out


def _load_name_set(name, col="municipality"):
    return {ckey(r.get(col, "")) for r in _read_csv(name) if r.get(col)}


COMMUNE_SHARE = _load_commune_share()
VILLAGE_MAP = _load_villages()
TOURIST = _load_name_set("tourist_communes.csv")
TOURIST_EXCLUDED = _load_name_set("tourist_excluded.csv")
TOURIST_STRICT = os.environ.get("TOURIST_STRICT", "") == "1"

# Starter frozen set for well known resorts, used only as a fallback when a
# commune is not in the ARE file (for example an unmapped village name).
FROZEN_FALLBACK = {
    ckey(x) for x in (
        "Zermatt", "Saas-Fee", "Saas-Grund", "St. Moritz", "Davos", "Verbier",
        "Nendaz", "Crans-Montana", "Leukerbad", "Saanen", "Grindelwald",
        "Lauterbrunnen", "Wengen", "Villars-sur-Ollon", "Leysin", "Zweisimmen",
        "Adelboden", "Arosa", "Laax", "Flims", "Engelberg",
    )
}


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_postcodes():
    """(postcode, locality key) -> (commune, canton), plus a per-postcode
    fallback holding the commune with the largest address share."""
    exact, by_plz = {}, {}
    for r in _read_csv("postcodes.csv"):
        entry = (r["commune"], r["canton"])
        exact[(r["postcode"], ckey(r["locality"]))] = entry
        share = float(r.get("share") or 0)
        if r["postcode"] not in by_plz or share > by_plz[r["postcode"]][0]:
            by_plz[r["postcode"]] = (share, entry)
    return exact, {k: v[1] for k, v in by_plz.items()}


def locate_postcode(postcode, locality=""):
    """Political commune and canton for a Swiss postcode, or ("", "")."""
    exact, by_plz = _load_postcodes()
    plz = str(postcode or "").strip()
    return exact.get((plz, ckey(locality))) or by_plz.get(plz) or ("", "")


def resolve_commune(muni: str) -> str:
    """Map a village name to its political commune, or return it unchanged."""
    return VILLAGE_MAP.get(ckey(muni), muni)


def commune_status(muni: str) -> dict:
    """Second home status: frozen, near, open, or unknown, plus the percentage.

    The ARE Status flag is authoritative when present; otherwise the raw
    percentage is used against the 20 and 17 thresholds.
    """
    key = ckey(resolve_commune(muni))
    rec = COMMUNE_SHARE.get(key)
    if rec is not None:
        pct = rec["pct"]
        restricted = rec["restricted"]
        if restricted is not None:
            if rec["in_review"]:
                status = "near"
            elif restricted == 1:
                status = "frozen"
            else:
                status = "open"
        elif pct is not None:
            if pct > 20:
                status = "frozen"
            elif pct >= FROZEN_NEAR:
                status = "near"
            else:
                status = "open"
        else:
            status = "unknown"
        return {"status": status, "pct": pct}
    if key in FROZEN_FALLBACK:
        return {"status": "frozen", "pct": None}
    return {"status": "unknown", "pct": None}


def is_tourist(muni: str):
    """Tri-state tourist gate. False = confirmed not designated (hard stop),
    True = confirmed designated, None = unknown (most communes are designated)."""
    key = ckey(resolve_commune(muni))
    if key in TOURIST_EXCLUDED:
        return False
    if TOURIST and key in TOURIST:
        return True
    if TOURIST and TOURIST_STRICT:
        return False
    return None


def resale_hold_years(canton: str) -> int:
    return RESALE_HOLD.get((canton or "").upper(), 0)


def target_cantons() -> list:
    return [c for c in ALLOWED_CANTONS if c in PRIMARY_TARGETS]


def passes_bounds(rooms, price) -> bool:
    if rooms is not None and not (FILTERS["rooms_min"] <= rooms <= FILTERS["rooms_max"]):
        return False
    if price is not None and price > FILTERS["price_max"]:
        return False
    return True
