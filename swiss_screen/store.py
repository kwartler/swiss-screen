"""Cache store. A single JSON file keyed by listing id, chosen over a binary so
it diffs cleanly in git when the Action commits it back. Change detection is a
content hash over price, title, and description, so unchanged listings are
skipped on the next run."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def content_hash(listing: dict) -> str:
    basis = f"{listing.get('price_chf')}|{listing.get('title')}|{listing.get('description')}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def load_cache(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1, sort_keys=True)


def upsert(cache: dict, listing: dict, det: dict, run_ts: str) -> bool:
    """Insert or update a classified listing. Returns True if brand new."""
    lid = listing["listing_id"]
    existing = cache.get(lid)
    is_new = existing is None
    first_seen = run_ts if is_new else existing.get("first_seen", run_ts)
    record = dict(listing)
    record.update({
        "eligible": det["eligible"],
        "rules_eligible": det["rules_eligible"],
        "llm_eligible": det["llm_eligible"],
        "align": det["align"],
        "method": det["method"],
        "snippet": det["snippet"],
        "build_type": det["build"],
        "confidence": det["confidence"],
        "llm_ok": det.get("llm_ok", False),
        "content_hash": content_hash(listing),
        "first_seen": first_seen,
        "last_seen": run_ts,
    })
    cache[lid] = record
    return is_new
