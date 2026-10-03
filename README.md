# Swiss foreign-eligible property screen

Screens Swiss resort listings for the ones a non-resident foreigner may buy as a
holiday home under Lex Koller and the Second Homes Act, then publishes a map and
a sortable list as a static web page. A GitHub Action runs it on a schedule and
deploys to GitHub Pages.

## What it produces

A single page (`site/index.html`) with three tabs:

- **Map** (OpenStreetMap via Leaflet): one marker per eligible listing, colored
  by buy status (green existing/resale, amber managed rental, rust new-build
  primary, grey closed to non-resident buyers). Click a marker to jump to its
  card.
- **Listings**: status cards with the regulatory badges, filters, and a CSV
  download.
- **Rental estimate**: wired as a seam, content lands next (ADR times occupancy,
  net of fees).

Plus `site/foreign_eligible_listings.csv` for the full eligible set.

## How eligibility is decided

Two tiers, both reading the listing text:

1. Regex over the standard agent phrases ("Verkauf an Auslaender moeglich", etc.)
   in German, French, Italian, English.
2. Sonnet via OpenRouter, which must quote a verbatim snippet from the listing.

Both run on every listing; the eligible set is the superset, and an alignment
badge shows whether the two agreed. Two regulatory gates then apply per commune:
the Second Homes share (ARE data, over 20 percent is frozen to new build) and
the Lex Koller tourist-location gate (cantonal; some resorts, Zermatt the known
case, are closed to non-resident buyers entirely).

## Run locally

    pip install -r requirements.txt
    python -m swiss_screen.pipeline --source mock --all-cantons --no-llm
    # open site/index.html

Flags: `--source mock|apify`, `--cantons VS,VD`, `--all-cantons`, `--no-llm`,
`--no-geocode`. Set `OPENROUTER_API_KEY` to turn on the Sonnet tier,
`APIFY_TOKEN` to use the live source.

## Put it on GitHub

1. Create an empty repo on GitHub (private is fine; the Pages site is still
   public, so keep secrets out of the committed output).
2. Push this directory:

       git init && git add -A
       git commit -m "Swiss foreign-eligible property screen"
       git branch -M main
       git remote add origin git@github.com:<you>/<repo>.git
       git push -u origin main

3. In the repo: Settings, Pages, set Source to "GitHub Actions".
4. Optional secrets (Settings, Secrets and variables, Actions):
   - `APIFY_TOKEN` to pull live Homegate data. Without it the Action builds from
     the bundled sample so the site still deploys.
   - `OPENROUTER_API_KEY` to run the LLM tier. Optional variable
     `OPENROUTER_MODEL` to pin a model.
5. The workflow runs nightly (03:17 UTC) or on demand from the Actions tab
   (Run workflow, choose source and whether to sweep all cantons). It commits
   the refreshed cache and coordinates back, which also keeps the schedule alive.

## Coordinates

Map pins use commune centroids in `data/commune_coords.csv`. A seed set ships
for the main resort communes. On a live run the pipeline geocodes any new
commune once via OpenStreetMap Nominatim and commits it back, so each commune is
geocoded at most once. Local mock runs skip geocoding and use the seed.

## Reference data

- `data/communes.csv`: real ARE Wohnungsinventar (31 March 2026), all 17
  eligible cantons, 1,420 communes. Regenerate yearly with
  `python build_communes.py` against the new `ZWG_<year>_Q1.xlsx`.
- `data/villages.csv`: village to political commune map (Wengen to Lauterbrunnen,
  etc.). Curated for VS/GR/VD/BE; extend for other cantons as needed.
- `data/tourist_excluded.csv`: communes closed to non-resident foreign buyers
  (ships with Zermatt). `data/tourist_communes.csv`: optional positive allowlist.

## Scope and honest limits

- Sweep size is small: filtered to 1 to 3.5 rooms, under CHF 850k, under 200 m²,
  BUY only. Across all 17 cantons that is hundreds of listings, not millions.
- The commune second-home gate covers all 17 cantons. The village map and
  tourist lists are curated only for VS/GR/VD/BE; elsewhere a village resolves to
  its own name and the tourist gate reads "verify".
- The Apify source is a third-party scraper (gray area; confirm Homegate's Terms
  before relying on it). It is not a stable contract and can break when the site
  changes; the pipeline warns on an empty live sweep.
- This surfaces candidates and explains why each qualifies. It does not replace a
  Swiss notary. Confirm any single purchase, and its permit path, with one.
