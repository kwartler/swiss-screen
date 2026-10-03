# AGENTS.md

Guidance for AI coding agents working in this repo. The project screens Swiss
property listings for non-resident foreign-buyer eligibility (Lex Koller plus
the Second Homes Act) and publishes a static map and list to GitHub Pages via a
scheduled GitHub Action.

## Setup

- Python 3.12. `pip install -r requirements.txt` (only `openpyxl`; everything
  else is standard library).
- No dev server. The output is a static page; build it and open the file.

## Build / run

- Build the site: `python -m swiss_screen.pipeline --source mock --all-cantons --no-llm`
  writes `site/index.html` and `site/foreign_eligible_listings.csv`.
- Flags: `--source mock|apify`, `--cantons VS,VD`, `--all-cantons`, `--chunks N`,
  `--no-llm`, `--no-geocode`, `--cache`, `--out`, `--csv`.
- Regenerate commune data from a new ARE workbook: `python build_communes.py
  [path/to/ZWG_<year>_Q1.xlsx]` (defaults to `data/ZWG_2026_Q1.xlsx`).
- There is no test suite yet. Before considering a change done, run the mock
  build above and confirm it exits 0, the eligible count is unchanged unless you
  meant to change it, and `site/index.html` still has the map markers and cards
  (grep `var POINTS=` and `class="card`).

## Directory map

- `swiss_screen/` the package: `config.py` (canton allowlist, filters, commune/
  village/tourist resolution), `detector.py` (two-tier eligibility), `fetch.py`
  (mock + Apify sources), `geocode.py` (commune centroids), `store.py` (JSON
  cache), `report.py` (tabbed HTML + Leaflet map + CSV), `pipeline.py` (entry).
- `data/` reference and state: `communes.csv` (ARE second-home shares, real),
  `villages.csv`, `tourist_excluded.csv`, `tourist_communes.csv`,
  `commune_coords.csv` (map centroids), `sample_listings.json` (mock),
  `cache.json` (run state, committed by the Action), `ZWG_2026_Q1.xlsx` (ARE
  source).
- `site/` build output, uploaded to Pages by the Action (gitignored).
- `.github/workflows/publish.yml` the scheduled run-and-deploy workflow.

## Code style

- Python: standard library first, add a dependency only when it clearly earns
  its place. Keep modules single-purpose and importable without side effects
  (all work happens under `pipeline.main()` or `if __name__ == "__main__"`).
- Formatting rule for all output, code comments and docs: no em dashes; use a
  hyphen only for a true compound word, never as a pause. Reword with commas,
  parentheses, colons, or separate sentences.
- If any R is added here, follow Ted's R conventions: base R over tidyverse,
  explicit `else` blocks, explicit `return()` in functions, and `1:length(x)` or
  `1:nrow(x)` rather than `seq_along()`/`seq_len()`.

## Data and secrets

- Never hardcode or commit API keys. `APIFY_TOKEN` and `OPENROUTER_API_KEY` are
  read from the environment (GitHub Actions secrets in CI).
- Never silently substitute fabricated, random, or stale data when a live call
  fails. The pipeline's contract: on a failed Apify fetch, log the error and
  skip that canton; on an all-empty live sweep, print the WARNING (do not let an
  empty result masquerade as an empty market). `--source mock` is an explicit,
  labeled fallback, never an automatic one.
- The LLM tier must keep its hallucination guard: a positive eligibility call
  must quote a verbatim snippet that appears in the listing text, or it is
  discarded. Do not weaken this.

## Regulatory logic (do not regress)

- Two independent gates per commune: Second Homes share (`communes.csv`, over 20
  percent is frozen to new build) and the Lex Koller tourist-location gate
  (cantonal). Keep them separate; a commune can be open on one and closed on the
  other.
- The tourist gate is tri-state: confirmed-excluded (hard stop, e.g. Zermatt),
  confirmed-designated, or unknown (verify). Unknown must never render as a
  green light. Adding entries to `tourist_excluded.csv` only tightens, which is
  the safe direction.
- `villages.csv` resolves a listing locality to its political commune before any
  commune lookup. Validate new commune names against `communes.csv` (the ARE
  spellings are authoritative).

## Deployment gotchas

- Pages source must be set to "GitHub Actions" (not a branch).
- `site/.nojekyll` must stay, or Pages' Jekyll step can drop files.
- The Action commits `data/cache.json` and `data/commune_coords.csv` back to the
  repo; that commit also keeps the scheduled workflow from being auto-disabled
  after 60 days of inactivity. Keep `[skip ci]` in that commit message so it does
  not trigger another run.
- Geocoding (OpenStreetMap Nominatim) only runs on live sources and needs open
  egress, so it works in the Action but not in a restricted sandbox. Respect
  Nominatim's 1 request/second limit (already enforced in `geocode.py`).

## Constraints

- Apify is a paid third-party scraper of Homegate, roughly CHF 1.80 per 1,000
  results, and is not a stable contract: it can break when the site changes.
- The sweep is intentionally small (1 to 3.5 rooms, under CHF 850k, under
  200 m2, BUY), hundreds of listings across all 17 cantons, not millions.

## Commits

- Conventional prefixes (`feat:`, `fix:`, `chore:`, `docs:`). AI-driven commits
  are fine. Keep automated cache commits as `chore: ... [skip ci]`.
