"""Pipeline entrypoint. Fetch -> classify (reads listing text) -> cache ->
attach commune coordinates -> render the tabbed HTML report and a CSV.

Run:
    python -m swiss_screen.pipeline --source mock --all-cantons --no-llm
    python -m swiss_screen.pipeline --source flatfox --all-cantons   # live, free
    python -m swiss_screen.pipeline --source apify        # needs APIFY_TOKEN
Set OPENROUTER_API_KEY to turn on the Sonnet tier.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

from . import config, store
from .detector import LLM_FAILURES, classify
from .fetch import fetch
from .geocode import ensure_coords
from .report import render_report
from .config import resolve_commune

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "site", "index.html")
DEFAULT_CACHE = os.path.join(ROOT, "data", "cache.json")
# Sample listings get their own cache so a local mock run never leaks into
# the live data the Action commits.
MOCK_CACHE = os.path.join(ROOT, "data", "cache_mock.json")
DEFAULT_CSV = os.path.join(ROOT, "site", "foreign_eligible_listings.csv")


def cantons_for_weekday(all_cantons, weekday, chunks=5):
    if not all_cantons:
        return []
    per = max(1, (len(all_cantons) + chunks - 1) // chunks)
    idx = weekday % chunks
    return all_cantons[idx * per: idx * per + per]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Swiss foreign-eligible property screen")
    ap.add_argument("--source", default="mock", choices=["mock", "flatfox", "apify"])
    ap.add_argument("--cantons", default="", help="comma list, overrides schedule")
    ap.add_argument("--all-cantons", action="store_true")
    ap.add_argument("--chunks", type=int, default=5)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-geocode", action="store_true", help="skip network geocoding")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--csv", default=DEFAULT_CSV)
    args = ap.parse_args(argv)

    if args.cache is None:
        args.cache = MOCK_CACHE if args.source == "mock" else DEFAULT_CACHE
    use_llm = not args.no_llm and bool(os.environ.get("OPENROUTER_API_KEY"))
    if args.cantons:
        cantons = [c.strip().upper() for c in args.cantons.split(",") if c.strip()]
    elif args.all_cantons:
        cantons = config.target_cantons()
    else:
        weekday = datetime.date.today().weekday()
        cantons = cantons_for_weekday(config.target_cantons(), weekday, args.chunks)

    run_ts = store.now_iso()
    cache = store.load_cache(args.cache)

    fetched = processed = new_count = 0
    for canton in cantons:
        try:
            listings = list(fetch(args.source, canton))
        except RuntimeError as exc:
            print(f"[{canton}] fetch error: {exc}", file=sys.stderr)
            continue
        for listing in listings:
            fetched += 1
            h = store.content_hash(listing)
            cached = cache.get(listing["listing_id"])
            llm_pending = use_llm and not cached.get("llm_ok") if cached else False
            if cached and cached.get("content_hash") == h and not llm_pending:
                cached["last_seen"] = run_ts
                continue
            det = classify(listing, use_llm=use_llm)
            if store.upsert(cache, listing, det, run_ts):
                new_count += 1
            processed += 1
            if processed % 25 == 0:
                # Checkpoint so a timeout never discards paid LLM work.
                store.save_cache(args.cache, cache)

    store.save_cache(args.cache, cache)

    if args.source != "mock" and fetched == 0:
        print("WARNING: live source returned zero listings across all swept cantons. "
              "This usually signals a broken feed, not an empty market.", file=sys.stderr)

    # Coordinates for the map: resolve each eligible listing's commune, then
    # ensure all are geocoded (cached). Network geocoding is on for live runs.
    eligible = [r for r in cache.values() if r.get("eligible") is True]
    communes = sorted({resolve_commune(r.get("municipality", "")) for r in eligible})
    allow_net = (not args.no_geocode) and args.source != "mock"
    coords = ensure_coords(communes, allow_network=allow_net)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    _, csv_text = render_report(cache, cantons, run_ts, processed, args.out, coords=coords,
                                source=args.source)
    with open(args.csv, "w", encoding="utf-8", newline="") as fh:
        fh.write(csv_text)

    print(f"cantons swept : {', '.join(cantons)}")
    print(f"fetched       : {fetched}")
    print(f"scanned (new/changed): {processed}")
    print(f"brand new     : {new_count}")
    print(f"eligible      : {len(eligible)}")
    if use_llm:
        print(f"llm failures  : {len(LLM_FAILURES)}")
    print(f"report        : {args.out}")
    print(f"csv           : {args.csv}")


if __name__ == "__main__":
    main()
